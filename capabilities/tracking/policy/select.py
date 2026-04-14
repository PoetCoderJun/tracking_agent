#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.infra.config import load_settings
from capabilities.llm_client import call_model, parse_json_block
from capabilities.tracking.artifacts.crop import save_target_crop
from capabilities.tracking.artifacts.visualization import save_detection_visualization
from capabilities.tracking.policy.prompt_templates import (
    TRACKING_RUNTIME_CONFIG_PATH,
    load_tracking_runtime_config,
    render_prompt_template,
)
from capabilities.tracking.state.memory import (
    empty_tracking_memory,
    read_tracking_memory_snapshot,
    tracking_memory_flash_prompt_text,
)
from world.perception import recent_frames


DEFAULT_CONFIG_PATH = TRACKING_RUNTIME_CONFIG_PATH
CHAT_HISTORY_LIMIT = 12
TRACKING_SELECT_MODEL = "qwen3.5-flash"
SELECT_MODEL_MAX_ATTEMPTS = 2
EXPLICIT_TARGET_ID_PATTERNS = (
    re.compile(r"\b(?:id|ID)\s*[:=]?\s*(\d+)\b"),
    re.compile(r"(?:id|ID)\s*为\s*(\d+)"),
    re.compile(r"(\d+)\s*号"),
)


@dataclass(frozen=True)
class DetectionRecord:
    track_id: int
    bbox: List[int]
    score: float


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def optional_text(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def normalized_frame(frame: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(frame, dict):
        return None
    frame_id = optional_text(frame.get("frame_id"))
    image_path = optional_text(frame.get("image_path"))
    if frame_id is None or image_path is None:
        return None

    detections: List[Dict[str, Any]] = []
    for detection in frame.get("detections", []):
        raw_track_id = detection.get("track_id")
        if raw_track_id in (None, ""):
            continue
        track_id = int(raw_track_id)
        detections.append(
            {
                "track_id": track_id,
                "bounding_box_id": track_id,
                "bbox": [int(value) for value in detection["bbox"]],
                "score": float(detection.get("score", 1.0)),
                "label": str(detection.get("label", "person")),
            }
        )

    return {
        "frame_id": frame_id,
        "timestamp_ms": int(frame.get("timestamp_ms", 0)),
        "image_path": image_path,
        "detections": detections,
    }


def normalized_track_ids(raw_track_ids: Any) -> List[int]:
    normalized: List[int] = []
    seen: set[int] = set()
    for track_id in list(raw_track_ids or []):
        try:
            candidate = int(track_id)
        except (TypeError, ValueError):
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        normalized.append(candidate)
    return normalized


def load_tracking_context(session_file: Path) -> Dict[str, Any]:
    raw_session = load_json(session_file)
    raw_state = dict(raw_session.get("state") or {})
    capabilities = dict(raw_state.get("capabilities") or {})
    tracking_state = dict((capabilities.get("tracking-init") or {}))
    excluded_track_ids = normalized_track_ids(tracking_state.get("excluded_track_ids"))
    state_root = session_file.resolve().parents[2]
    session_id = str(raw_session["session_id"])
    frames = recent_frames(
        state_root=state_root,
        excluded_track_ids=excluded_track_ids,
    )

    latest_target_id = tracking_state.get("latest_target_id")
    if latest_target_id is not None:
        latest_target_id = int(latest_target_id)
    memory_snapshot = read_tracking_memory_snapshot(state_root=state_root, session_id=session_id)

    return {
        "session_id": session_id,
        "target_description": str(tracking_state.get("target_description", "")),
        "memory": memory_snapshot.get("memory", empty_tracking_memory()),
        "latest_target_id": latest_target_id,
        "front_crop_path": optional_text(memory_snapshot.get("front_crop_path")),
        "back_crop_path": optional_text(memory_snapshot.get("back_crop_path")),
        "excluded_track_ids": excluded_track_ids,
        "chat_history": [
            {
                "role": str(entry.get("role", "")),
                "text": str(entry.get("text", "")),
                "timestamp": str(entry.get("timestamp", "")),
            }
            for entry in (raw_session.get("conversation_history") or [])[-CHAT_HISTORY_LIMIT:]
        ],
        "frames": frames,
    }


def load_tracking_context_file(tracking_context_file: Path) -> Dict[str, Any]:
    payload = load_json(tracking_context_file)
    excluded_track_ids = normalized_track_ids(payload.get("excluded_track_ids"))
    return {
        "session_id": str(payload["session_id"]),
        "target_description": str(payload.get("target_description", "")),
        "memory": payload.get("memory", ""),
        "latest_target_id": payload.get("latest_target_id"),
        "front_crop_path": optional_text(payload.get("front_crop_path")),
        "back_crop_path": optional_text(payload.get("back_crop_path")),
        "recovery_mode": bool(payload.get("recovery_mode", False)),
        "missing_target_id": payload.get("missing_target_id"),
        "excluded_track_ids": excluded_track_ids,
        "chat_history": [
            {
                "role": str(entry.get("role", "")),
                "text": str(entry.get("text", "")),
                "timestamp": str(entry.get("timestamp", "")),
            }
            for entry in list(payload.get("chat_history") or [])[-CHAT_HISTORY_LIMIT:]
            if isinstance(entry, dict)
        ],
        "frames": [
            normalized
            for normalized in (normalized_frame(frame) for frame in list(payload.get("frames") or []))
            if normalized is not None
        ],
    }


def latest_frame(context: Dict[str, Any]) -> Dict[str, Any]:
    frames = context.get("frames") or []
    if not frames:
        raise ValueError("Tracking context does not contain any frames")
    return frames[-1]


def frame_for_behavior(context: Dict[str, Any], behavior: str) -> Dict[str, Any]:
    return latest_frame(context)


def track_note(context: Dict[str, Any]) -> str:
    latest_target_id = context.get("latest_target_id")
    if latest_target_id in (None, ""):
        return "当前调用的是 track：说明上一轮目标已经找不到或当前证据不够稳定；默认保守，不要轻易改绑。"
    return (
        f"当前调用的是 track：上一轮绑定的 target id {int(latest_target_id)} 已经找不到，或者当前证据不够稳定。"
        " 默认保守：只有多个关键身份特征同时一致且无明显冲突时才允许改绑；否则优先 wait。"
    )


def session_has_active_target(context: Dict[str, Any]) -> bool:
    return context.get("latest_target_id") not in (None, "", [])


def candidate_summary(detections: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for detection in detections:
        raw_track_id = detection.get("track_id")
        if raw_track_id in (None, ""):
            continue
        lines.append(
            f"- ID {int(raw_track_id)}: bbox={[int(value) for value in detection['bbox']]}, score={float(detection.get('score', 1.0)):.2f}"
        )
    if not lines:
        return "无候选人。"
    return "\n".join(lines)


def explicit_target_id(text: str) -> Optional[int]:
    normalized = text.strip()
    if not normalized:
        return None
    for pattern in EXPLICIT_TARGET_ID_PATTERNS:
        match = pattern.search(normalized)
        if match:
            return int(match.group(1))
    return None


def recent_dialogue_text(chat_history: List[Dict[str, Any]], *, limit: int = 6) -> str:
    items: List[str] = []
    for entry in list(chat_history or [])[-limit:]:
        role = str(entry.get("role", "")).strip() or "unknown"
        text = str(entry.get("text", "")).strip()
        if text:
            items.append(f"{role}: {text}")
    return "\n".join(items) if items else "(无)"


def ensure_session_dirs(artifacts_root: Path, session_id: str) -> Dict[str, Path]:
    session_root = artifacts_root / "sessions" / session_id
    artifacts_dir = session_root / "agent_artifacts"
    frames_dir = session_root / "reference_frames"
    crops_dir = session_root / "reference_crops"
    for path in (artifacts_dir, frames_dir, crops_dir):
        path.mkdir(parents=True, exist_ok=True)
    return {
        "session_root": session_root,
        "artifacts_dir": artifacts_dir,
        "frames_dir": frames_dir,
        "crops_dir": crops_dir,
    }


def build_rewrite_memory_input(
    *,
    behavior: str,
    crop_path: Path,
    frame_paths: List[str],
    frame_id: str,
    target_id: int,
    confirmation_reason: str | None = None,
    candidate_checks: List[Dict[str, Any]] | None = None,
    desired_reference_view: str | None = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "task": "init" if behavior == "init" else "update",
        "crop_path": str(crop_path),
        "frame_paths": list(frame_paths),
        "frame_id": frame_id,
        "target_id": int(target_id),
    }
    reason = optional_text(confirmation_reason)
    if reason is not None:
        payload["confirmation_reason"] = reason
    if candidate_checks:
        payload["candidate_checks"] = list(candidate_checks)
    desired_view = optional_text(desired_reference_view)
    if desired_view is not None:
        payload["desired_reference_view"] = desired_view
    return payload


def rewrite_memory_frame_paths(
    *,
    behavior: str,
    current_frame_path: Path,
) -> List[str]:
    del behavior
    return [str(current_frame_path)]


def persist_reference_frame(frame_path: Path, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if frame_path.resolve() != output_path.resolve():
        shutil.copy2(frame_path, output_path)
    return output_path


def select_detection_by_track_id(detections: List[DetectionRecord], target_id: int) -> Optional[DetectionRecord]:
    for detection in detections:
        if int(detection.track_id) == int(target_id):
            return detection
    return None


def _bbox_intersects(a: List[int], b: List[int]) -> bool:
    left = max(int(a[0]), int(b[0]))
    top = max(int(a[1]), int(b[1]))
    right = min(int(a[2]), int(b[2]))
    bottom = min(int(a[3]), int(b[3]))
    return right > left and bottom > top


def _selected_box_overlaps_others(
    *,
    detections: List[DetectionRecord],
    target_id: int,
) -> bool:
    selected = select_detection_by_track_id(detections, target_id)
    if selected is None:
        return False
    for detection in detections:
        if int(detection.track_id) == int(target_id):
            continue
        if _bbox_intersects(list(selected.bbox), list(detection.bbox)):
            return True
    return False


def detection_records(detections: List[Dict[str, Any]]) -> List[DetectionRecord]:
    records: List[DetectionRecord] = []
    for detection in detections:
        raw_track_id = detection.get("track_id")
        if raw_track_id in (None, ""):
            continue
        records.append(
            DetectionRecord(
                track_id=int(raw_track_id),
                bbox=[int(value) for value in detection["bbox"]],
                score=float(detection.get("score", 1.0)),
            )
        )
    return records


def normalize_select_result(result: Dict[str, Any]) -> Dict[str, Any]:
    target_id = result.get("bounding_box_id")
    if target_id is None:
        target_id = result.get("target_id")
    if target_id is not None:
        target_id = int(target_id)

    needs_clarification = bool(result.get("needs_clarification", False))
    clarification_question = optional_text(result.get("clarification_question"))
    if needs_clarification and clarification_question is None:
        raise ValueError("needs_clarification=true requires clarification_question")

    decision = optional_text(result.get("decision"))
    if decision not in {"track", "ask", "wait"}:
        raise ValueError(f"decision must be one of track|ask|wait, got: {decision!r}")

    text = optional_text(result.get("text"))
    if text is None:
        raise ValueError("text is required")

    reason = optional_text(result.get("reason"))
    reject_reason = optional_text(result.get("reject_reason")) or ""

    if decision == "track":
        if target_id is None:
            raise ValueError("track decision requires bounding_box_id")
        found = True
    else:
        found = False
        target_id = None
        if decision == "wait":
            if not reject_reason and text is not None:
                reject_reason = text
        if decision == "ask":
            reject_reason = ""

    normalized = {
        "found": found and target_id is not None,
        "target_id": target_id,
        "bounding_box_id": target_id,
        "text": text,
        "reject_reason": reject_reason,
        "needs_clarification": needs_clarification,
        "clarification_question": clarification_question,
        "decision": decision,
        "candidate_checks": list(result.get("candidate_checks") or []),
    }
    if reason is not None:
        normalized["reason"] = reason
    return normalized


def _collect_matched_candidates(
    *,
    candidate_checks: List[Dict[str, Any]],
    detections: List[DetectionRecord],
) -> List[int]:
    """收集所有 status 为 match 的候选 ID（按 candidate_checks 顺序）。"""
    matched_ids: List[int] = []
    seen: set[int] = set()
    for item in list(candidate_checks or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("status", "")).strip() != "match":
            continue
        candidate_id = item.get("bounding_box_id")
        if candidate_id in (None, ""):
            continue
        resolved_id = int(candidate_id)
        if select_detection_by_track_id(detections, resolved_id) is None:
            continue
        if resolved_id in seen:
            continue
        seen.add(resolved_id)
        matched_ids.append(resolved_id)
    return matched_ids


def _unique_matched_candidate_id(
    *,
    candidate_checks: List[Dict[str, Any]],
    detections: List[DetectionRecord],
) -> Optional[int]:
    matched_ids = _collect_matched_candidates(
        candidate_checks=candidate_checks,
        detections=detections,
    )
    if len(matched_ids) != 1:
        return None
    return matched_ids[0]


def _build_clarification_for_multiple_matches(
    *,
    matched_ids: List[int],
    candidate_checks: List[Dict[str, Any]],
) -> str:
    """基于 candidate_checks 中的 evidence 构建多目标澄清问题。"""
    if not matched_ids:
        return "当前没有匹配的候选人，请补充特征描述。"
    
    # 收集每个匹配候选的 evidence
    id_to_evidence: Dict[int, str] = {}
    for item in list(candidate_checks or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("status", "")).strip() != "match":
            continue
        candidate_id = item.get("bounding_box_id")
        if candidate_id in (None, ""):
            continue
        resolved_id = int(candidate_id)
        if resolved_id not in matched_ids:
            continue
        evidence = str(item.get("evidence", "")).strip()
        if evidence:
            id_to_evidence[resolved_id] = evidence
    
    if len(matched_ids) == 1:
        return f"请确认是否跟踪 ID 为 {matched_ids[0]} 的目标？"
    
    # 构建问题
    parts: List[str] = []
    for idx, cid in enumerate(matched_ids, 1):
        evidence = id_to_evidence.get(cid, "")
        if evidence:
            parts.append(f"第{idx}个（ID {cid}）：{evidence}")
        else:
            parts.append(f"第{idx}个（ID {cid}）")
    
    question = f"当前有 {len(matched_ids)} 个匹配的目标：\n" + "\n".join(parts)
    question += "\n请问跟踪哪一个？请回复目标编号或描述特征。"
    return question


def explicit_target_result(*, target_id: int, matched: Optional[DetectionRecord], behavior: str) -> Dict[str, Any]:
    if matched is None:
        question = f"当前画面里没有 ID 为 {target_id} 的候选人，请确认目标 ID。"
        return {
            "found": False,
            "target_id": None,
            "bounding_box_id": None,
            "text": question,
            "reject_reason": "",
            "needs_clarification": True,
            "clarification_question": question,
            "decision": "ask",
        }

    text = f"已确认跟踪 ID 为 {target_id} 的目标。" if behavior == "init" else f"已切换为跟踪 ID 为 {target_id} 的目标。"
    return {
        "found": True,
        "target_id": int(target_id),
        "bounding_box_id": int(target_id),
        "text": text,
        "reject_reason": "",
        "needs_clarification": False,
        "clarification_question": None,
        "decision": "track",
    }


def normalize_invalid_model_selection(
    *,
    normalized: Dict[str, Any],
    detections: List[DetectionRecord],
    behavior: str,
) -> Dict[str, Any]:
    if not normalized.get("found"):
        return normalized

    target_id = normalized.get("target_id")
    if target_id in (None, ""):
        return normalized
    if select_detection_by_track_id(detections, int(target_id)) is not None:
        return normalized

    rescued_target_id = _unique_matched_candidate_id(
        candidate_checks=list(normalized.get("candidate_checks") or []),
        detections=detections,
    )
    if rescued_target_id is not None:
        return {
            **{key: value for key, value in normalized.items() if key != "reason"},
            "found": True,
            "target_id": rescued_target_id,
            "bounding_box_id": rescued_target_id,
            "decision": "track",
            "text": "已确认继续跟踪该目标。" if behavior == "track" else "已确认目标。",
            "reject_reason": "",
            "needs_clarification": False,
            "clarification_question": None,
        }

    invalid_reason = f"模型返回的目标 ID {int(target_id)} 不在当前候选列表中，不能直接绑定。"

    if behavior == "init":
        question = "当前候选框不足以稳定确认目标，请补充特征或直接指定候选框 ID。"
        return {
            **{key: value for key, value in normalized.items() if key != "reason"},
            "found": False,
            "target_id": None,
            "bounding_box_id": None,
            "text": question,
            "reject_reason": "",
            "needs_clarification": True,
            "clarification_question": question,
            "decision": "ask",
        }

    return {
        **{key: value for key, value in normalized.items() if key != "reason"},
        "found": False,
        "target_id": None,
        "bounding_box_id": None,
        "text": "当前证据不足，保持等待原目标重新出现。",
        "reject_reason": invalid_reason,
        "needs_clarification": False,
        "clarification_question": None,
        "decision": "wait",
    }


def enforce_conservative_track_decision(
    *,
    normalized: Dict[str, Any],
    detections: List[DetectionRecord],
) -> Dict[str, Any]:
    if str(normalized.get("decision", "")).strip() != "track":
        return normalized
    target_id = normalized.get("target_id")
    if target_id in (None, ""):
        return normalized
    if not _selected_box_overlaps_others(detections=detections, target_id=int(target_id)):
        return normalized

    overlap_reason = "当前选中的目标框与其他候选框发生重叠，不能把这个 tracker box 视为可信的单人目标框。"
    return {
        **{key: value for key, value in normalized.items() if key != "reason"},
        "found": False,
        "target_id": None,
        "bounding_box_id": None,
        "text": "当前目标框与其他候选框重叠，先保持等待。",
        "reject_reason": overlap_reason,
        "needs_clarification": False,
        "clarification_question": None,
        "decision": "wait",
    }


def reference_crop_assets(context: Dict[str, Any]) -> List[Dict[str, Any]]:
    def collect(candidates: tuple[tuple[str, str], ...]) -> List[Dict[str, Any]]:
        assets: List[Dict[str, Any]] = []
        seen: set[Path] = set()
        for key, label in candidates:
            text = optional_text(context.get(key))
            if text is None:
                continue
            path = Path(text)
            if not path.exists() or path in seen:
                continue
            assets.append({"key": key, "label": label, "path": path})
            seen.add(path)
        return assets

    return collect(
        (
            ("front_crop_path", "当前 memory 的正面 crop"),
            ("back_crop_path", "当前 memory 的背面 crop"),
        )
    )

def reference_crops_note(reference_assets: List[Dict[str, Any]]) -> str:
    if not reference_assets:
        return "无可用的正面/背面参考 crop。"
    return "\n".join(f"- 第{index}张图：{asset['label']}" for index, asset in enumerate(reference_assets, start=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one init/track localization turn for tracking.")
    parser.add_argument("--mode", choices=("init", "track"), required=True)
    parser.add_argument("--tracking-context-file", default="")
    parser.add_argument("--session-file", default="")
    parser.add_argument("--target-description", default="")
    parser.add_argument("--user-text", default="")
    parser.add_argument("--env-file", default=".ENV")
    parser.add_argument("--artifacts-root", default="./.runtime/pi-agent")
    return parser.parse_args()


def _select_with_model(
    *,
    settings: Any,
    model_name: str,
    instruction: str,
    image_paths: list[Path],
    output_contract: str,
    max_tokens: int,
) -> tuple[Dict[str, Any], float]:
    last_error: Exception | None = None
    total_elapsed_seconds = 0.0

    for _ in range(SELECT_MODEL_MAX_ATTEMPTS):
        output = call_model(
            api_key=settings.api_key,
            base_url=settings.base_url,
            timeout_seconds=settings.timeout_seconds,
            model=model_name,
            instruction=instruction,
            image_paths=image_paths,
            output_contract=output_contract,
            max_tokens=max_tokens,
        )
        total_elapsed_seconds += float(output["elapsed_seconds"])
        try:
            return normalize_select_result(parse_json_block(output["response_text"])), total_elapsed_seconds
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = exc

    if last_error is not None:
        raise last_error
    raise RuntimeError("select model returned no result")


def execute_select_tool(
    *,
    session_file: Path | None = None,
    tracking_context_file: Path | None = None,
    tracking_context: Dict[str, Any] | None = None,
    behavior: str,
    arguments: Dict[str, Any],
    env_file: Path,
    artifacts_root: Path,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> Dict[str, Any]:
    if behavior not in {"init", "track"}:
        raise ValueError(f"Unsupported select behavior: {behavior}")

    if tracking_context is not None:
        context = dict(tracking_context)
    elif tracking_context_file is not None:
        context = load_tracking_context_file(tracking_context_file)
    else:
        if session_file is None:
            raise ValueError("select_target requires tracking_context, tracking_context_file, or session_file")
        context = load_tracking_context(session_file)

    if behavior == "track" and not session_has_active_target(context):
        raise ValueError("track tool requires an active target")

    frame = frame_for_behavior(context, behavior)
    frame_path = Path(str(frame["image_path"]))
    detections = detection_records(frame.get("detections", []))
    session_dirs = ensure_session_dirs(artifacts_root, str(context["session_id"]))
    persisted_current_frame_path = persist_reference_frame(
        frame_path,
        session_dirs["artifacts_dir"] / f"{frame_path.stem}_current.jpg",
    )
    overlay_path = session_dirs["artifacts_dir"] / f"{frame['frame_id']}_overlay.jpg"
    save_detection_visualization(persisted_current_frame_path, detections, overlay_path)

    explicit_request_text = (
        str(arguments.get("target_description", "")).strip()
        if behavior == "init"
        else str(arguments.get("user_text", "")).strip()
    )
    requested_target_id = explicit_target_id(explicit_request_text)
    config = load_tracking_runtime_config(config_path)

    if behavior == "init":
        target_description = str(arguments.get("target_description", "")).strip()
        if not target_description:
            raise ValueError("init requires target_description")
        if requested_target_id is not None:
            normalized = explicit_target_result(
                target_id=requested_target_id,
                matched=select_detection_by_track_id(detections, requested_target_id),
                behavior=behavior,
            )
            elapsed_seconds = 0.0
        else:
            settings = load_settings(env_file)
            instruction = render_prompt_template(
                prompt_key="tracking_init_select_prompt",
                target_description=target_description,
                candidates=candidate_summary(frame.get("detections", [])),
            )
            normalized, elapsed_seconds = _select_with_model(
                settings=settings,
                model_name=TRACKING_SELECT_MODEL,
                instruction=instruction,
                image_paths=[overlay_path],
                output_contract=config["contracts"]["tracking_init_select_result"],
                max_tokens=int(config["limits"]["tracking_select_max_tokens"]),
            )
            normalized = normalize_invalid_model_selection(
                normalized=normalized,
                detections=detections,
                behavior=behavior,
            )
            # init 模式下：如果用户未明确指定目标，且检测到多个匹配候选，触发澄清问题
            if (
                normalized.get("found")
                and requested_target_id is None
                and not normalized.get("needs_clarification")
            ):
                matched_ids = _collect_matched_candidates(
                    candidate_checks=list(normalized.get("candidate_checks") or []),
                    detections=detections,
                )
                if len(matched_ids) > 1:
                    question = _build_clarification_for_multiple_matches(
                        matched_ids=matched_ids,
                        candidate_checks=list(normalized.get("candidate_checks") or []),
                    )
                    normalized["found"] = False
                    normalized["target_id"] = None
                    normalized["bounding_box_id"] = None
                    normalized["decision"] = "ask"
                    normalized["needs_clarification"] = True
                    normalized["clarification_question"] = question
                    normalized["text"] = question
                    normalized.pop("reason", None)
    else:
        if requested_target_id is not None:
            normalized = explicit_target_result(
                target_id=requested_target_id,
                matched=select_detection_by_track_id(detections, requested_target_id),
                behavior=behavior,
            )
            elapsed_seconds = 0.0
        else:
            settings = load_settings(env_file)
            reference_assets = reference_crop_assets(context)
            reference_paths = [Path(asset["path"]) for asset in reference_assets]
            instruction = render_prompt_template(
                prompt_key="continuous_tracking_select_prompt",
                memory=tracking_memory_flash_prompt_text(context.get("memory", "")),
                reference_crops_note=reference_crops_note(reference_assets),
                candidates=candidate_summary(frame.get("detections", [])),
            )
            normalized, elapsed_seconds = _select_with_model(
                settings=settings,
                model_name=TRACKING_SELECT_MODEL,
                instruction=instruction,
                image_paths=[*reference_paths, overlay_path],
                output_contract=config["contracts"]["continuous_tracking_select_result"],
                max_tokens=int(config["limits"]["tracking_select_max_tokens"]),
            )
            normalized = normalize_invalid_model_selection(
                normalized=normalized,
                detections=detections,
                behavior=behavior,
            )
            normalized = enforce_conservative_track_decision(
                normalized=normalized,
                detections=detections,
            )

    if behavior == "track" and normalized["decision"] == "ask" and requested_target_id is None:
        normalized["found"] = False
        normalized["target_id"] = None
        normalized["bounding_box_id"] = None
        normalized["needs_clarification"] = False
        normalized["clarification_question"] = None
        normalized["decision"] = "wait"
        normalized["reject_reason"] = normalized.get("reject_reason") or "当前是 track：原目标已找不到或证据不够稳定；证据不足时不能改绑。"
        if not normalized["text"]:
            normalized["text"] = "当前证据不足，保持等待原目标重新出现。"
        normalized.pop("reason", None)

    crop_path = None
    rewrite_memory_input = None
    if normalized["found"]:
        for detection in detections:
            if int(detection.track_id) != int(normalized["target_id"]):
                continue
            crop_path = session_dirs["crops_dir"] / f"{frame_path.stem}_id_{normalized['target_id']}.jpg"
            save_target_crop(persisted_current_frame_path, detection.bbox, crop_path)
            current_frame_reference_path = persist_reference_frame(
                persisted_current_frame_path,
                session_dirs["frames_dir"] / f"{frame_path.stem}.jpg",
            )
            rewrite_memory_input = build_rewrite_memory_input(
                behavior=behavior,
                crop_path=crop_path,
                frame_paths=rewrite_memory_frame_paths(
                    behavior=behavior,
                    current_frame_path=current_frame_reference_path,
                ),
                frame_id=str(frame["frame_id"]),
                target_id=int(normalized["target_id"]),
                confirmation_reason=None,
                candidate_checks=list(normalized.get("candidate_checks") or []),
            )
            break

    payload = {
        "behavior": behavior,
        "text": normalized["text"],
        "frame_id": str(frame["frame_id"]),
        "target_id": normalized["target_id"],
        "bounding_box_id": normalized["bounding_box_id"],
        "found": normalized["found"],
        "needs_clarification": normalized["needs_clarification"],
        "clarification_question": normalized["clarification_question"],
        "memory": str(context.get("memory", "")),
        "reject_reason": str(normalized.get("reject_reason", "")).strip(),
        "candidate_checks": list(normalized.get("candidate_checks") or []),
        "decision": normalized["decision"],
        "target_description": (
            str(arguments.get("target_description", "")).strip()
            if behavior == "init"
            else str(context.get("target_description", ""))
        ),
        "rewrite_memory_input": rewrite_memory_input,
        "elapsed_seconds": elapsed_seconds,
        "pending_question": normalized["clarification_question"] if normalized["decision"] == "ask" else None,
    }
    if normalized.get("reason") not in (None, ""):
        payload["reason"] = str(normalized.get("reason")).strip()
    return payload


def main() -> int:
    args = parse_args()
    tracking_context_file = optional_text(args.tracking_context_file)
    payload = execute_select_tool(
        session_file=None if tracking_context_file else Path(args.session_file),
        tracking_context_file=None if not tracking_context_file else Path(tracking_context_file),
        behavior=args.mode,
        arguments={
            "target_description": args.target_description,
            "user_text": args.user_text,
        },
        env_file=Path(args.env_file),
        artifacts_root=Path(args.artifacts_root),
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
