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
from skills.tracking.detection_visualization import save_detection_visualization
from skills.tracking.memory_format import tracking_memory_display_text, tracking_memory_flash_prompt_text
from skills.tracking.target_crop import save_target_crop


SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = SKILL_ROOT / "references" / "robot-agent-config.json"
CHAT_HISTORY_LIMIT = 12
TRACK_CANDIDATE_CROP_LIMIT = 3
TRACK_REBIND_SCORE_THRESHOLD = 0.64
TRACK_REBIND_MARGIN_THRESHOLD = 0.06
TRACK_ID_STAY_BONUS = 0.08
TRACK_SPATIAL_WEIGHT = 0.18
TRACK_APPEARANCE_WEIGHT = 0.82


@dataclass(frozen=True)
class DetectionRecord:
    track_id: int
    bbox: List[int]
    score: float


EXPLICIT_TARGET_ID_PATTERNS = (
    re.compile(r"\b(?:id|ID)\s*[:=]?\s*(\d+)\b"),
    re.compile(r"(?:id|ID)\s*为\s*(\d+)"),
    re.compile(r"(\d+)\s*号"),
)


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


def load_agent_config(config_path: Path = DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    return json.loads(config_path.read_text(encoding="utf-8"))


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

    frames: List[Dict[str, Any]] = []
    for frame in raw_session.get("recent_frames", []):
        normalized = normalized_frame(frame)
        if normalized is not None:
            frames.append(normalized)

    latest_target_id = tracking_state.get("latest_target_id")
    if latest_target_id is not None:
        latest_target_id = int(latest_target_id)

    return {
        "session_id": str(raw_session["session_id"]),
        "target_description": str(tracking_state.get("target_description", "")),
        "memory": tracking_memory_display_text(tracking_state.get("latest_memory", "")),
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
    return {
        "session_id": str(payload["session_id"]),
        "target_description": str(payload.get("target_description", "")),
        "memory": str(payload.get("memory", "")),
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
        "candidate_track_id_floor_exclusive": payload.get("candidate_track_id_floor_exclusive"),
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
            for normalized in (
                normalized_frame(frame) for frame in list(payload.get("frames") or [])
            )
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


def _recovery_note(context: Dict[str, Any]) -> str:
    if not bool(context.get("recovery_mode")):
        return "当前不是找回模式。"
    missing_target_id = context.get("missing_target_id")
    note = f"当前处于找回模式：上一轮绑定的 track id {missing_target_id} 已暂时不在画面里。"
    note += " 业务逻辑层已经提前完成候选过滤；你不要根据 id 大小做推理，只需要判断当前画面是否已经出现了与历史目标具备强连续性证据的候选。"
    note += " 如果只是短时遮挡、局部不可见、或证据不足，请优先返回 wait，等待原目标重新出现。"
    return note


def session_has_active_target(context: Dict[str, Any]) -> bool:
    return bool(context.get("latest_target_id") is not None and context.get("latest_confirmed_frame_path"))


def candidate_summary(detections: List[Dict[str, Any]]) -> str:
    if not detections:
        return "- 无候选人"
    return "\n".join(
        f"- bounding_box_id={int(detection['track_id'])}: bbox={list(detection['bbox'])}, score={float(detection.get('score', 1.0)):.2f}"
        for detection in detections
    )


def _track_candidate_crop_detections(detections: List[DetectionRecord]) -> List[DetectionRecord]:
    ordered = sorted(detections, key=lambda detection: float(detection.score), reverse=True)
    return ordered[:TRACK_CANDIDATE_CROP_LIMIT]


def _candidate_crop_note(candidate_detections: List[DetectionRecord]) -> str:
    if not candidate_detections:
        return "当前没有额外候选 crop。"
    lines = [
        "第三张及之后的图片是当前候选人的单人 crop，顺序与下面列表完全一致：",
    ]
    for index, detection in enumerate(candidate_detections, start=3):
        lines.append(f"- 第 {index} 张图 -> bounding_box_id={int(detection.track_id)}")
    return "\n".join(lines)


def explicit_target_id(text: Any) -> Optional[int]:
    normalized = str(text or "").strip()
    if not normalized:
        return None
    for pattern in EXPLICIT_TARGET_ID_PATTERNS:
        match = pattern.search(normalized)
        if match:
            return int(match.group(1))
    return None


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
    clarification_question = str(result.get("clarification_question", "")).strip() or None
    if needs_clarification and clarification_question is None:
        clarification_question = "请进一步说明你指的是哪一个候选人。"
    decision = str(result.get("decision", "")).strip() or None
    if decision not in {"track", "ask", "wait"}:
        if found and target_id is not None:
            decision = "track"
        elif needs_clarification:
            decision = "ask"
        else:
            decision = "wait"

    text = str(result.get("text", "")).strip()
    reason = str(result.get("reason", "")).strip()
    reject_reason = str(result.get("reject_reason", "")).strip()
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


def _explicit_target_result(*, target_id: int, matched: Optional[DetectionRecord], behavior: str) -> Dict[str, Any]:
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

    if behavior == "init":
        text = f"已确认跟踪 ID 为 {target_id} 的目标。"
    else:
        text = f"已切换为跟踪 ID 为 {target_id} 的目标。"
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


def _normalize_invalid_model_selection(
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


def _recent_dialogue_text(chat_history: List[Dict[str, Any]], *, limit: int = 6) -> str:
    items: List[str] = []
    for entry in list(chat_history or [])[-limit:]:
        role = str(entry.get("role", "")).strip() or "unknown"
        text = str(entry.get("text", "")).strip()
        if not text:
            continue
        items.append(f"{role}: {text}")
    return "\n".join(items) if items else "(无)"


def ensure_session_dirs(artifacts_root: Path, session_id: str) -> Dict[str, Path]:
    session_root = artifacts_root / session_id
    paths = {
        "artifacts_dir": session_root / "agent_artifacts",
        "crops_dir": session_root / "reference_crops",
        "frames_dir": session_root / "reference_frames",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def build_rewrite_memory_input(
    *,
    behavior: str,
    crop_path: Path,
    frame_paths: List[str],
    frame_id: str,
    target_id: int,
) -> Dict[str, Any]:
    return {
        "task": "init" if behavior == "init" else "update",
        "crop_path": str(crop_path),
        "frame_paths": frame_paths,
        "frame_id": frame_id,
        "target_id": int(target_id),
    }


def rewrite_memory_frame_paths(
    *,
    behavior: str,
    current_frame_path: Path,
    latest_confirmed_frame_path: Optional[str],
) -> List[str]:
    return [str(current_frame_path)]


def _persist_reference_frame(frame_path: Path, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if frame_path.resolve() != output_path.resolve():
        shutil.copyfile(frame_path, output_path)
    return output_path


def _save_candidate_crops(
    *,
    frame_path: Path,
    detections: List[DetectionRecord],
    output_dir: Path,
    frame_id: str,
) -> List[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: List[Path] = []
    for detection in detections:
        output_path = output_dir / f"{frame_id}_candidate_{int(detection.track_id)}.jpg"
        save_target_crop(frame_path, detection.bbox, output_path)
        paths.append(output_path)
    return paths


def _normalized_bbox(bbox: Any) -> Optional[List[int]]:
    if not isinstance(bbox, list) or len(bbox) != 4:
        return None
    try:
        return [int(value) for value in bbox]
    except (TypeError, ValueError):
        return None


def _crop_for_matching(image_path: Path, bbox: List[int]) -> Image.Image:
    image = Image.open(image_path).convert("RGB")
    width, height = image.size
    x1, y1, x2, y2 = [int(value) for value in bbox]
    left = max(0, min(width, x1))
    top = max(0, min(height, y1))
    right = max(left + 1, min(width, x2))
    bottom = max(top + 1, min(height, y2))
    return image.crop((left, top, right, bottom))


def _appearance_signature(image: Image.Image) -> List[float]:
    normalized = ImageOps.fit(image.convert("RGB"), (32, 64))
    histogram = normalized.histogram()
    total = float(sum(histogram)) or 1.0
    return [float(value) / total for value in histogram]


def _cosine_similarity(left: List[float], right: List[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = sum(a * a for a in left) ** 0.5
    right_norm = sum(b * b for b in right) ** 0.5
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return numerator / (left_norm * right_norm)


def _bbox_continuity_score(previous_bbox: Optional[List[int]], current_bbox: List[int]) -> float:
    if previous_bbox is None:
        return 0.5
    px1, py1, px2, py2 = previous_bbox
    cx1, cy1, cx2, cy2 = current_bbox
    prev_center = ((px1 + px2) / 2.0, (py1 + py2) / 2.0)
    curr_center = ((cx1 + cx2) / 2.0, (cy1 + cy2) / 2.0)
    prev_width = max(1.0, float(px2 - px1))
    prev_height = max(1.0, float(py2 - py1))
    curr_width = max(1.0, float(cx2 - cx1))
    curr_height = max(1.0, float(cy2 - cy1))
    center_distance = (((prev_center[0] - curr_center[0]) ** 2) + ((prev_center[1] - curr_center[1]) ** 2)) ** 0.5
    normalized_distance = center_distance / max(prev_width, prev_height, curr_width, curr_height)
    size_ratio = min(prev_width, curr_width) / max(prev_width, curr_width)
    height_ratio = min(prev_height, curr_height) / max(prev_height, curr_height)
    distance_score = max(0.0, 1.0 - normalized_distance)
    return max(0.0, min(1.0, (distance_score * 0.6) + (size_ratio * 0.2) + (height_ratio * 0.2)))


def _reference_crop_assets(context: Dict[str, Any]) -> List[Dict[str, Any]]:
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


def _reference_crop_paths(context: Dict[str, Any]) -> List[Path]:
    return [Path(asset["path"]) for asset in _reference_crop_assets(context)]


def _reference_crops_note(reference_assets: List[Dict[str, Any]]) -> str:
    if not reference_assets:
        return "无额外历史正面/背面参考 crop。"

    lines: List[str] = []
    for index, asset in enumerate(reference_assets, start=2):
        lines.append(f"- 第{index}张图：{asset['label']}")
    return "\n".join(lines)


def _deterministic_track_result(
    *,
    context: Dict[str, Any],
    frame_path: Path,
    detections: List[DetectionRecord],
) -> Dict[str, Any]:
    if not detections:
        question = "当前画面中没有检测到任何候选人，请稍后重试或重新初始化目标。"
        return {
            "found": False,
            "target_id": None,
            "bounding_box_id": None,
            "text": question,
            "reason": "当前画面中没有候选人。",
            "reject_reason": "当前帧没有任何候选人，无法建立与历史目标的身份连续性。",
            "needs_clarification": False,
            "clarification_question": None,
            "decision": "wait",
        }

    reference_paths = _reference_crop_paths(context)
    if not reference_paths:
        question = "当前缺少目标参考图，请重新初始化目标。"
        return {
            "found": False,
            "target_id": None,
            "bounding_box_id": None,
            "text": question,
            "reason": "缺少可用于重绑定的目标参考图。",
            "reject_reason": "缺少历史参考 crop 或参考帧，当前无法把候选人与既有目标身份做稳定比对。",
            "needs_clarification": False,
            "clarification_question": None,
            "decision": "wait",
        }

    reference_signatures = [
        _appearance_signature(Image.open(path).convert("RGB"))
        for path in reference_paths
    ]
    previous_bbox = _normalized_bbox(context.get("latest_confirmed_bbox"))
    previous_target_id = context.get("latest_target_id")
    scored: List[Dict[str, Any]] = []
    for detection in detections:
        candidate_crop = _crop_for_matching(frame_path, detection.bbox)
        candidate_signature = _appearance_signature(candidate_crop)
        appearance_score = max(
            _cosine_similarity(reference_signature, candidate_signature)
            for reference_signature in reference_signatures
        )
        spatial_score = _bbox_continuity_score(previous_bbox, detection.bbox)
        score = (appearance_score * TRACK_APPEARANCE_WEIGHT) + (spatial_score * TRACK_SPATIAL_WEIGHT)
        if previous_target_id not in (None, "") and int(detection.track_id) == int(previous_target_id):
            score += TRACK_ID_STAY_BONUS
        scored.append(
            {
                "track_id": int(detection.track_id),
                "appearance_score": appearance_score,
                "spatial_score": spatial_score,
                "score": score,
            }
        )

    scored.sort(key=lambda item: item["score"], reverse=True)
    best = scored[0]
    second_best = scored[1] if len(scored) > 1 else None
    margin = best["score"] - (0.0 if second_best is None else second_best["score"])
    if best["score"] < TRACK_REBIND_SCORE_THRESHOLD:
        question = "当前候选人与历史目标的外观连续性不足，请重新指定目标或重新初始化。"
        return {
            "found": False,
            "target_id": None,
            "bounding_box_id": None,
            "text": question,
            "reason": f"最佳候选分数过低（score={best['score']:.3f}）。",
            "reject_reason": (
                f"最佳候选 ID {best['track_id']} 的综合分数仅为 {best['score']:.3f}，"
                f"其中 appearance={best['appearance_score']:.3f}、spatial={best['spatial_score']:.3f}，"
                "还不足以支持继续绑定。"
            ),
            "needs_clarification": False,
            "clarification_question": None,
            "decision": "wait",
        }
    if second_best is not None and margin < TRACK_REBIND_MARGIN_THRESHOLD:
        question = "当前有多个候选人与历史目标过于接近，请指定目标 ID 或补充更稳定的外观特征。"
        return {
            "found": False,
            "target_id": None,
            "bounding_box_id": None,
            "text": question,
            "reason": f"最佳候选与次佳候选过于接近（margin={margin:.3f}）。",
            "reject_reason": (
                f"最佳候选 ID {best['track_id']} 与次佳候选 ID {second_best['track_id']} 的综合分差只有 {margin:.3f}，"
                "当前无法把两者稳定区分。"
            ),
            "needs_clarification": False,
            "clarification_question": None,
            "decision": "wait",
        }

    rebind_reason = (
        f"外观连续性最高的候选为 ID {best['track_id']} "
        f"(appearance={best['appearance_score']:.3f}, spatial={best['spatial_score']:.3f}, score={best['score']:.3f})。"
    )
    if previous_target_id not in (None, "") and int(best["track_id"]) != int(previous_target_id):
        text = f"已将跟踪目标从 ID {int(previous_target_id)} 重绑定到 ID {best['track_id']}。"
    else:
        text = f"已确认继续跟踪 ID {best['track_id']}。"
    return {
        "found": True,
        "target_id": int(best["track_id"]),
        "bounding_box_id": int(best["track_id"]),
        "text": text,
        "reason": rebind_reason,
        "reject_reason": "",
        "needs_clarification": False,
        "clarification_question": None,
        "decision": "track",
    }


def execute_select_tool(
    *,
    session_file: Path | None = None,
    memory_file: Path | None = None,
    tracking_context_file: Path | None = None,
    behavior: str,
    arguments: Dict[str, Any],
    env_file: Path,
    artifacts_root: Path,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> Dict[str, Any]:
    if behavior not in {"init", "track"}:
        raise ValueError(f"Unsupported select behavior: {behavior}")

    if tracking_context_file is not None:
        context = load_tracking_context_file(tracking_context_file)
    else:
        if session_file is None or memory_file is None:
            raise ValueError("select_target requires tracking_context_file or both session_file and memory_file")
        context = load_tracking_context(session_file, memory_file)

    if behavior == "track" and not session_has_active_target(context):
        raise ValueError("track tool requires an active target")

    frame = frame_for_behavior(context, behavior)
    frame_path = Path(str(frame["image_path"]))
    detections = detection_records(frame.get("detections", []))
    session_dirs = ensure_session_dirs(artifacts_root, str(context["session_id"]))
    persisted_current_frame_path = _persist_reference_frame(
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

    if behavior == "init":
        target_description = str(arguments.get("target_description", "")).strip()
        if not target_description:
            raise ValueError("init requires target_description")
        config = load_agent_config(config_path)
        if requested_target_id is not None:
            normalized = _explicit_target_result(
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
                model_name=settings.main_model,
                instruction=instruction,
                image_paths=[overlay_path],
                output_contract=config["contracts"]["select_init_target"],
                max_tokens=int(config["limits"]["select_max_tokens"]),
            )
            normalized = _normalize_invalid_model_selection(
                normalized=normalized,
                detections=detections,
                behavior=behavior,
            )
    else:
        config = load_agent_config(config_path)
        if requested_target_id is not None:
            normalized = _explicit_target_result(
                target_id=requested_target_id,
                matched=select_detection_by_track_id(detections, requested_target_id),
                behavior=behavior,
            )
            elapsed_seconds = 0.0
        else:
            settings = load_settings(env_file)
            confirmed_frame_path = optional_text(context.get("latest_confirmed_frame_path"))
            if confirmed_frame_path is None:
                raise ValueError("track tool requires latest_confirmed_frame_path")
            reference_frame_path = Path(confirmed_frame_path)
            if not reference_frame_path.exists():
                raise ValueError(f"Missing latest_confirmed_frame_path: {reference_frame_path}")
            reference_crop_assets = _reference_crop_assets(context)
            reference_crop_paths = [Path(asset["path"]) for asset in reference_crop_assets]
            candidate_crop_detections = _track_candidate_crop_detections(detections)
            candidate_crop_paths = _save_candidate_crops(
                frame_path=persisted_current_frame_path,
                detections=candidate_crop_detections,
                output_dir=session_dirs["artifacts_dir"],
                frame_id=str(frame["frame_id"]),
            )
            instruction = str(config["prompts"]["track_skill_prompt"]).format(
                memory=tracking_memory_flash_prompt_text(context.get("memory", "")),
                latest_target_id=context.get("latest_target_id"),
                reference_crops_note=_reference_crops_note(reference_crop_assets),
                candidates=candidate_summary(frame.get("detections", [])),
                user_text=str(arguments.get("user_text", "")).strip() or "(无)",
                recent_dialogue=_recent_dialogue_text(list(context.get("chat_history") or [])),
                recovery_note=_recovery_note(context),
                candidate_crops_note=_candidate_crop_note(candidate_crop_detections),
            )
            normalized, elapsed_seconds = _select_with_model(
                settings=settings,
                model_name=settings.main_model,
                instruction=instruction,
                image_paths=[reference_frame_path, *reference_crop_paths, overlay_path, *candidate_crop_paths],
                output_contract=config["contracts"]["select_track_target"],
                max_tokens=int(config["limits"]["select_max_tokens"]),
            )
            normalized = _normalize_invalid_model_selection(
                normalized=normalized,
                detections=detections,
                behavior=behavior,
            )

    if behavior == "track" and bool(context.get("recovery_mode")) and normalized["decision"] == "ask":
        normalized["found"] = False
        normalized["target_id"] = None
        normalized["bounding_box_id"] = None
        normalized["needs_clarification"] = False
        normalized["clarification_question"] = None
        normalized["decision"] = "wait"
        normalized["reject_reason"] = normalized.get("reject_reason") or "恢复模式下当前证据不足，不能从 ask 升级为重绑定。"
        if not normalized["text"]:
            normalized["text"] = "当前证据不足，保持等待原目标重新出现。"
        if normalized["reason"]:
            normalized["reason"] = f"{normalized['reason']} 恢复模式下证据不足，已降级为 wait。".strip()
        else:
            normalized["reason"] = "恢复模式下证据不足，已降级为 wait。"

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
            confirmed_frame_path = _persist_reference_frame(
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
