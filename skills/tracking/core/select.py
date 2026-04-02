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

from backend.config import load_settings
from backend.llm_client import call_model, parse_json_block
from skills.tracking.core.visualization import save_detection_visualization
from skills.tracking.core.memory import tracking_memory_flash_prompt_text
from skills.tracking.core.crop import save_target_crop


SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = SKILL_ROOT / "references" / "robot-agent-config.json"
CHAT_HISTORY_LIMIT = 12
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


def load_agent_config(config_path: Path = DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    return json.loads(config_path.read_text(encoding="utf-8"))


def optional_text(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if text.lower() in {"none", "null"}:
        return None
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
        track_id = int(detection["track_id"])
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


def load_tracking_context(session_file: Path, memory_file: Path) -> Dict[str, Any]:
    raw_session = load_json(session_file)
    memory_payload = load_json(memory_file) if memory_file.exists() else {}
    tracking_state = dict(((memory_payload.get("skill_cache") or {}).get("tracking") or {}))

    frames = [
        normalized
        for normalized in (normalized_frame(frame) for frame in raw_session.get("recent_frames", []))
        if normalized is not None
    ]

    latest_target_id = tracking_state.get("latest_target_id")
    if latest_target_id is not None:
        latest_target_id = int(latest_target_id)

    return {
        "session_id": str(raw_session["session_id"]),
        "target_description": str(tracking_state.get("target_description", "")),
        "memory": tracking_state.get("latest_memory", ""),
        "latest_target_id": latest_target_id,
        "latest_target_crop": optional_text(tracking_state.get("latest_target_crop")),
        "latest_front_target_crop": optional_text(tracking_state.get("latest_front_target_crop")),
        "latest_back_target_crop": optional_text(tracking_state.get("latest_back_target_crop")),
        "latest_confirmed_frame_path": optional_text(tracking_state.get("latest_confirmed_frame_path")),
        "identity_target_crop": optional_text(tracking_state.get("identity_target_crop")),
        "latest_confirmed_bbox": tracking_state.get("latest_confirmed_bbox"),
        "init_frame_snapshot": normalized_frame(tracking_state.get("init_frame_snapshot")),
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
    excluded_track_ids: List[int] = []
    for track_id in list(payload.get("excluded_track_ids") or []):
        try:
            excluded_track_ids.append(int(track_id))
        except (TypeError, ValueError):
            continue
    return {
        "session_id": str(payload["session_id"]),
        "target_description": str(payload.get("target_description", "")),
        "memory": payload.get("memory", ""),
        "latest_target_id": payload.get("latest_target_id"),
        "latest_target_crop": optional_text(payload.get("latest_target_crop")),
        "latest_front_target_crop": optional_text(payload.get("latest_front_target_crop")),
        "latest_back_target_crop": optional_text(payload.get("latest_back_target_crop")),
        "latest_confirmed_frame_path": optional_text(payload.get("latest_confirmed_frame_path")),
        "identity_target_crop": optional_text(payload.get("identity_target_crop")),
        "latest_confirmed_bbox": payload.get("latest_confirmed_bbox"),
        "init_frame_snapshot": normalized_frame(payload.get("init_frame_snapshot")),
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
    if behavior == "init":
        snapshot = context.get("init_frame_snapshot")
        if isinstance(snapshot, dict):
            return snapshot
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
    return bool(context.get("latest_target_id") is not None and context.get("latest_confirmed_frame_path"))


def candidate_summary(detections: List[Dict[str, Any]]) -> str:
    if not detections:
        return "无候选人。"
    return "\n".join(
        f"- ID {int(detection['track_id'])}: bbox={[int(value) for value in detection['bbox']]}, score={float(detection.get('score', 1.0)):.2f}"
        for detection in detections
    )


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
    return payload


def rewrite_memory_frame_paths(
    *,
    behavior: str,
    current_frame_path: Path,
    latest_confirmed_frame_path: Any,
) -> List[str]:
    if behavior == "init":
        return [str(current_frame_path)]
    latest_reference = optional_text(latest_confirmed_frame_path)
    if latest_reference is None:
        return [str(current_frame_path)]
    return [latest_reference, str(current_frame_path)]


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


def detection_records(detections: List[Dict[str, Any]]) -> List[DetectionRecord]:
    return [
        DetectionRecord(
            track_id=int(detection["track_id"]),
            bbox=[int(value) for value in detection["bbox"]],
            score=float(detection.get("score", 1.0)),
        )
        for detection in detections
    ]


def normalize_select_result(result: Dict[str, Any]) -> Dict[str, Any]:
    found = bool(result.get("found", False))
    target_id = result.get("bounding_box_id")
    if target_id is None:
        target_id = result.get("target_id")
    if target_id is not None:
        target_id = int(target_id)

    needs_clarification = bool(result.get("needs_clarification", False))
    clarification_question = optional_text(result.get("clarification_question"))
    if needs_clarification and clarification_question is None:
        clarification_question = "请进一步说明你指的是哪一个候选人。"

    decision = optional_text(result.get("decision"))
    if decision not in {"track", "ask", "wait"}:
        if found and target_id is not None:
            decision = "track"
        elif needs_clarification:
            decision = "ask"
        else:
            decision = "wait"

    text = optional_text(result.get("text")) or ""
    reason = optional_text(result.get("reason")) or ""
    reject_reason = optional_text(result.get("reject_reason")) or ""
    if not text:
        text = reason or ("我确认当前目标。" if found and target_id is not None else "我暂时无法确认目标。")
    if decision == "wait" and not reject_reason:
        reject_reason = reason

    return {
        "found": found and target_id is not None,
        "target_id": target_id,
        "bounding_box_id": target_id,
        "text": text,
        "reason": reason,
        "reject_reason": reject_reason,
        "needs_clarification": needs_clarification,
        "clarification_question": clarification_question,
        "decision": decision,
        "candidate_checks": list(result.get("candidate_checks") or []),
    }


def explicit_target_result(*, target_id: int, matched: Optional[DetectionRecord], behavior: str) -> Dict[str, Any]:
    if matched is None:
        question = f"当前画面里没有 ID 为 {target_id} 的候选人，请确认目标 ID。"
        return {
            "found": False,
            "target_id": None,
            "bounding_box_id": None,
            "text": question,
            "reason": "用户明确指定了目标 ID，但当前候选框中不存在该 ID。",
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
        "reason": "用户明确指定了候选框 ID。",
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

    invalid_reason = f"模型返回的目标 ID {int(target_id)} 不在当前候选列表中，不能直接绑定。"
    base_reason = str(normalized.get("reason", "")).strip()
    reason = f"{base_reason} {invalid_reason}".strip() if base_reason else invalid_reason

    if behavior == "init":
        question = "当前候选框不足以稳定确认目标，请补充特征或直接指定候选框 ID。"
        return {
            **normalized,
            "found": False,
            "target_id": None,
            "bounding_box_id": None,
            "text": question,
            "reason": reason,
            "reject_reason": "",
            "needs_clarification": True,
            "clarification_question": question,
            "decision": "ask",
        }

    return {
        **normalized,
        "found": False,
        "target_id": None,
        "bounding_box_id": None,
        "text": "当前证据不足，保持等待原目标重新出现。",
        "reason": reason,
        "reject_reason": invalid_reason,
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

    view_specific_assets = collect(
        (
            ("latest_front_target_crop", "最近保存的目标正面 crop"),
            ("latest_back_target_crop", "最近保存的目标背面 crop"),
        )
    )
    if view_specific_assets:
        return view_specific_assets
    return collect(
        (
            ("identity_target_crop", "身份基准 crop"),
            ("latest_target_crop", "最近一次确认的目标 crop"),
        )
    )


def should_reset_reference_crops(
    *,
    behavior: str,
    context: Dict[str, Any],
    target_id: Optional[int],
) -> bool:
    if target_id is None:
        return False
    if behavior == "init":
        return True
    previous_target_id = context.get("latest_target_id")
    if previous_target_id in (None, ""):
        return False
    return int(previous_target_id) != int(target_id)


def reference_crops_note(reference_assets: List[Dict[str, Any]]) -> str:
    if not reference_assets:
        return "无额外历史正面/背面参考 crop。"
    return "\n".join(f"- 第{index}张图：{asset['label']}" for index, asset in enumerate(reference_assets, start=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one init/track localization turn for tracking.")
    parser.add_argument("--mode", choices=("init", "track"), required=True)
    parser.add_argument("--tracking-context-file", default="")
    parser.add_argument("--session-file", default="")
    parser.add_argument("--memory-file", default="")
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
    return normalize_select_result(parse_json_block(output["response_text"])), output["elapsed_seconds"]


def execute_select_tool(
    *,
    session_file: Path | None = None,
    memory_file: Path | None = None,
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
        if session_file is None or memory_file is None:
            raise ValueError("select_target requires tracking_context, tracking_context_file, or both session_file and memory_file")
        context = load_tracking_context(session_file, memory_file)

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
    config = load_agent_config(config_path)

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
            instruction = str(config["prompts"]["init_skill_prompt"]).format(
                target_description=target_description,
                candidates=candidate_summary(frame.get("detections", [])),
            )
            normalized, elapsed_seconds = _select_with_model(
                settings=settings,
                model_name=settings.sub_model,
                instruction=instruction,
                image_paths=[overlay_path],
                output_contract=config["contracts"]["select_init_target"],
                max_tokens=int(config["limits"]["select_max_tokens"]),
            )
            normalized = normalize_invalid_model_selection(
                normalized=normalized,
                detections=detections,
                behavior=behavior,
            )
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
            instruction = str(config["prompts"]["track_skill_prompt"]).format(
                memory=tracking_memory_flash_prompt_text(context.get("memory", "")),
                latest_target_id=context.get("latest_target_id"),
                reference_crops_note=reference_crops_note(reference_assets),
                candidates=candidate_summary(frame.get("detections", [])),
                user_text=str(arguments.get("user_text", "")).strip() or "(无)",
                recent_dialogue=recent_dialogue_text(list(context.get("chat_history") or [])),
                track_note=track_note(context),
            )
            normalized, elapsed_seconds = _select_with_model(
                settings=settings,
                model_name=settings.main_model,
                instruction=instruction,
                image_paths=[*reference_paths, overlay_path],
                output_contract=config["contracts"]["select_track_target"],
                max_tokens=int(config["limits"]["select_max_tokens"]),
            )
            normalized = normalize_invalid_model_selection(
                normalized=normalized,
                detections=detections,
                behavior=behavior,
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
        if normalized["reason"]:
            normalized["reason"] = f"{normalized['reason']} 当前是 track：原目标已找不到或证据不够稳定，已降级为 wait。".strip()
        else:
            normalized["reason"] = "当前是 track：原目标已找不到或证据不够稳定，已降级为 wait。"

    crop_path = None
    rewrite_memory_input = None
    confirmed_frame_path = None
    confirmed_bbox = None
    identity_target_crop = None
    if normalized["found"]:
        for detection in detections:
            if int(detection.track_id) != int(normalized["target_id"]):
                continue
            crop_path = session_dirs["crops_dir"] / f"{frame_path.stem}_id_{normalized['target_id']}.jpg"
            save_target_crop(persisted_current_frame_path, detection.bbox, crop_path)
            confirmed_frame_path = persist_reference_frame(
                persisted_current_frame_path,
                session_dirs["frames_dir"] / f"{frame_path.stem}.jpg",
            )
            confirmed_bbox = [int(value) for value in detection.bbox]
            identity_target_crop = (
                str(crop_path)
                if behavior == "init" or not optional_text(context.get("identity_target_crop"))
                else optional_text(context.get("identity_target_crop"))
            )
            rewrite_memory_input = build_rewrite_memory_input(
                behavior=behavior,
                crop_path=crop_path,
                frame_paths=rewrite_memory_frame_paths(
                    behavior=behavior,
                    current_frame_path=confirmed_frame_path,
                    latest_confirmed_frame_path=context.get("latest_confirmed_frame_path"),
                ),
                frame_id=str(frame["frame_id"]),
                target_id=int(normalized["target_id"]),
                confirmation_reason=normalized.get("reason"),
                candidate_checks=list(normalized.get("candidate_checks") or []),
            )
            break

    return {
        "behavior": behavior,
        "text": normalized["text"],
        "frame_id": str(frame["frame_id"]),
        "target_id": normalized["target_id"],
        "bounding_box_id": normalized["bounding_box_id"],
        "found": normalized["found"],
        "needs_clarification": normalized["needs_clarification"],
        "clarification_question": normalized["clarification_question"],
        "memory": str(context.get("memory", "")),
        "reason": normalized["reason"],
        "reject_reason": str(normalized.get("reject_reason", "")).strip(),
        "candidate_checks": list(normalized.get("candidate_checks") or []),
        "decision": normalized["decision"],
        "latest_target_crop": None if crop_path is None else str(crop_path),
        "identity_target_crop": identity_target_crop,
        "confirmed_frame_path": None if confirmed_frame_path is None else str(confirmed_frame_path),
        "confirmed_bbox": confirmed_bbox,
        "reset_reference_crops": should_reset_reference_crops(
            behavior=behavior,
            context=context,
            target_id=normalized["target_id"],
        ),
        "target_description": (
            str(arguments.get("target_description", "")).strip()
            if behavior == "init"
            else str(context.get("target_description", ""))
        ),
        "rewrite_memory_input": rewrite_memory_input,
        "elapsed_seconds": elapsed_seconds,
        "pending_question": normalized["clarification_question"] if normalized["decision"] == "ask" else None,
    }


def main() -> int:
    args = parse_args()
    tracking_context_file = optional_text(args.tracking_context_file)
    payload = execute_select_tool(
        session_file=None if tracking_context_file else Path(args.session_file),
        memory_file=None if tracking_context_file else Path(args.memory_file),
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
