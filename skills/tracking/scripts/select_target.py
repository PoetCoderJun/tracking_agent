#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import load_settings
from backend.llm_client import call_model, parse_json_block
from skills.tracking.detection_visualization import save_detection_visualization
from skills.tracking.target_crop import save_target_crop


SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = SKILL_ROOT / "references" / "robot-agent-config.json"
CHAT_HISTORY_LIMIT = 12


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
    parser.add_argument("--session-file", required=True)
    parser.add_argument("--memory-file", required=True)
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


def load_tracking_context(session_file: Path, memory_file: Path) -> Dict[str, Any]:
    raw_session = load_json(session_file)
    memory_payload = load_json(memory_file) if memory_file.exists() else {}
    tracking_state = dict(((memory_payload.get("skill_cache") or {}).get("tracking") or {}))

    frames: List[Dict[str, Any]] = []
    for frame in raw_session.get("recent_frames", []):
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
        frames.append(
            {
                "frame_id": str(frame["frame_id"]),
                "timestamp_ms": int(frame["timestamp_ms"]),
                "image_path": str(frame["image_path"]),
                "detections": detections,
            }
        )

    latest_target_id = tracking_state.get("latest_target_id")
    if latest_target_id is not None:
        latest_target_id = int(latest_target_id)

    return {
        "session_id": str(raw_session["session_id"]),
        "target_description": str(tracking_state.get("target_description", "")),
        "memory": str(tracking_state.get("latest_memory", "")),
        "latest_target_id": latest_target_id,
        "latest_confirmed_frame_path": optional_text(tracking_state.get("latest_confirmed_frame_path")),
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


def latest_frame(context: Dict[str, Any]) -> Dict[str, Any]:
    frames = context.get("frames") or []
    if not frames:
        raise ValueError("Tracking context does not contain any frames")
    return frames[-1]


def session_has_active_target(context: Dict[str, Any]) -> bool:
    return bool(context.get("latest_target_id") is not None and context.get("latest_confirmed_frame_path"))


def candidate_summary(detections: List[Dict[str, Any]]) -> str:
    if not detections:
        return "- 无候选人"
    return "\n".join(
        f"- bounding_box_id={int(detection['track_id'])}: bbox={list(detection['bbox'])}, score={float(detection.get('score', 1.0)):.2f}"
        for detection in detections
    )


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

    text = str(result.get("text", "")).strip()
    reason = str(result.get("reason", "")).strip()
    if not text:
        text = reason or ("我确认当前目标。" if found and target_id is not None else "我暂时无法确认目标。")

    return {
        "found": found and target_id is not None,
        "target_id": target_id,
        "bounding_box_id": target_id,
        "text": text,
        "reason": reason,
        "needs_clarification": needs_clarification,
        "clarification_question": clarification_question,
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
            "needs_clarification": True,
            "clarification_question": question,
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
        "needs_clarification": False,
        "clarification_question": None,
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


def ensure_session_dirs(artifacts_root: Path, session_id: str) -> Dict[str, Path]:
    session_root = artifacts_root / session_id
    paths = {
        "artifacts_dir": session_root / "agent_artifacts",
        "crops_dir": session_root / "reference_crops",
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
    if behavior == "init" or not latest_confirmed_frame_path:
        return [str(current_frame_path)]
    previous_frame_path = Path(str(latest_confirmed_frame_path))
    if previous_frame_path == current_frame_path:
        return [str(current_frame_path)]
    return [str(previous_frame_path), str(current_frame_path)]


def execute_select_tool(
    *,
    session_file: Path,
    memory_file: Path,
    behavior: str,
    arguments: Dict[str, Any],
    env_file: Path,
    artifacts_root: Path,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> Dict[str, Any]:
    if behavior not in {"init", "track"}:
        raise ValueError(f"Unsupported select behavior: {behavior}")

    context = load_tracking_context(session_file, memory_file)

    if behavior == "track" and not session_has_active_target(context):
        raise ValueError("track tool requires an active target")

    frame = latest_frame(context)
    frame_path = Path(str(frame["image_path"]))
    detections = detection_records(frame.get("detections", []))
    session_dirs = ensure_session_dirs(artifacts_root, str(context["session_id"]))
    overlay_path = session_dirs["artifacts_dir"] / f"{frame['frame_id']}_overlay.jpg"
    save_detection_visualization(frame_path, detections, overlay_path)

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
    else:
        requested_text = str(arguments.get("user_text", "")).strip() or "持续跟踪"
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
            historical_frame_path = Path(str(context["latest_confirmed_frame_path"]))
            if not historical_frame_path.exists():
                raise ValueError(f"Missing latest_confirmed_frame_path: {historical_frame_path}")
            instruction = str(config["prompts"]["track_skill_prompt"]).format(
                memory=str(context.get("memory", "")) or "无",
                latest_target_id=context.get("latest_target_id"),
                candidates=candidate_summary(frame.get("detections", [])),
                user_text=requested_text,
                recent_dialogue="\n".join(
                    f"- {entry.get('role', 'unknown')}: {entry.get('text', '')}"
                    for entry in (context.get("chat_history") or [])
                )
                or "- 无",
            )
            normalized, elapsed_seconds = _select_with_model(
                settings=settings,
                model_name=settings.main_model,
                instruction=instruction,
                image_paths=[historical_frame_path, overlay_path],
                output_contract=config["contracts"]["select_track_target"],
                max_tokens=int(config["limits"]["select_max_tokens"]),
            )

    crop_path = None
    rewrite_memory_input = None
    if normalized["found"]:
        for detection in detections:
            if int(detection.track_id) != int(normalized["target_id"]):
                continue
            crop_path = session_dirs["crops_dir"] / f"{frame_path.stem}_id_{normalized['target_id']}.jpg"
            save_target_crop(frame_path, detection.bbox, crop_path)
            rewrite_memory_input = build_rewrite_memory_input(
                behavior=behavior,
                crop_path=crop_path,
                frame_paths=rewrite_memory_frame_paths(
                    behavior=behavior,
                    current_frame_path=frame_path,
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
        "pending_question": normalized["clarification_question"],
        "memory": str(context.get("memory", "")),
        "reason": normalized["reason"],
        "latest_target_crop": None if crop_path is None else str(crop_path),
        "target_description": (
            str(arguments.get("target_description", "")).strip()
            if behavior == "init"
            else str(context.get("target_description", ""))
        ),
        "rewrite_memory_input": rewrite_memory_input,
        "elapsed_seconds": elapsed_seconds,
    }


def main() -> int:
    args = parse_args()
    payload = execute_select_tool(
        session_file=Path(args.session_file),
        memory_file=Path(args.memory_file),
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
