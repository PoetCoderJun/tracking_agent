#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from tracking_agent.config import load_settings
from tracking_agent.detection_visualization import save_detection_visualization
from tracking_agent.memory_format import normalize_memory_markdown
from tracking_agent.target_crop import save_target_crop

from agent_common import call_model, load_agent_config, parse_json_block

SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = SKILL_ROOT / "references" / "robot-agent-config.json"
DEFAULT_TOOLS_PATH = SKILL_ROOT / "references" / "pi-agent-tools.json"


@dataclass(frozen=True)
class DetectionRecord:
    track_id: int
    bbox: List[int]
    score: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PI Agent adapter for the vision tracking skill.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    describe_parser = subparsers.add_parser("describe", help="Print the PI-facing tool manifest.")
    describe_parser.add_argument("--tools-path", default=str(DEFAULT_TOOLS_PATH))

    invoke_parser = subparsers.add_parser("invoke", help="Execute one skill tool against backend agent context.")
    invoke_parser.add_argument("--tool", choices=("reply", "init", "track", "rewrite_memory"), required=True)
    invoke_parser.add_argument("--context-file", required=True)
    invoke_parser.add_argument("--arguments-json", default=None)
    invoke_parser.add_argument("--arguments-file", default=None)
    invoke_parser.add_argument("--env-file", default=".ENV")
    invoke_parser.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH))
    invoke_parser.add_argument("--tools-path", default=str(DEFAULT_TOOLS_PATH))
    invoke_parser.add_argument("--artifacts-root", default="./runtime/pi-agent")

    return parser.parse_args()


def load_json_path(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_json_input(path_value: str) -> Dict[str, Any]:
    if path_value == "-":
        return json.loads(sys.stdin.read())
    return load_json_path(Path(path_value))


def load_arguments(arguments_json: Optional[str], arguments_file: Optional[str]) -> Dict[str, Any]:
    if arguments_json and arguments_file:
        raise ValueError("Provide only one of --arguments-json or --arguments-file")
    if arguments_file:
        return read_json_input(arguments_file)
    if arguments_json:
        return json.loads(arguments_json)
    return {}


def optional_text(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    return str(value).strip() or None


def extract_bounding_box_id(payload: Dict[str, Any]) -> Optional[int]:
    raw_value = payload.get("bounding_box_id")
    if raw_value is None:
        raw_value = payload.get("bbox_id")
    if raw_value is None:
        raw_value = payload.get("target_id")
    if raw_value is None:
        return None
    return int(raw_value)


def with_result_aliases(result: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if result is None:
        return None
    payload = dict(result)
    target_id = extract_bounding_box_id(payload)
    if target_id is not None:
        payload["target_id"] = target_id
        payload["bounding_box_id"] = target_id
    return payload


def build_working_context(raw_session: Dict[str, Any]) -> Dict[str, Any]:
    latest_result = with_result_aliases(raw_session.get("latest_result"))
    frames: List[Dict[str, Any]] = []
    for frame in raw_session.get("recent_frames", []):
        detections = []
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

    latest_target_id = raw_session.get("latest_target_id")
    if latest_target_id is not None:
        latest_target_id = int(latest_target_id)

    return {
        "session_id": str(raw_session["session_id"]),
        "device_id": str(raw_session.get("device_id", "")),
        "target_description": str(raw_session.get("target_description", "")),
        "memory": str(raw_session.get("latest_memory", "")),
        "latest_memory": str(raw_session.get("latest_memory", "")),
        "latest_target_id": latest_target_id,
        "latest_bounding_box_id": latest_target_id,
        "latest_target_crop": optional_text(raw_session.get("latest_target_crop")),
        "latest_confirmed_frame_path": optional_text(raw_session.get("latest_confirmed_frame_path")),
        "clarification_notes": [str(note) for note in raw_session.get("clarification_notes", [])],
        "conversation_history": [
            {
                "role": str(entry.get("role", "")),
                "text": str(entry.get("text", "")),
                "timestamp": str(entry.get("timestamp", "")),
            }
            for entry in raw_session.get("conversation_history", [])
        ],
        "pending_question": optional_text(raw_session.get("pending_question")),
        "latest_result": latest_result,
        "frames": frames,
        "raw_session": raw_session,
    }


def latest_frame(context: Dict[str, Any]) -> Dict[str, Any]:
    frames = context.get("frames", [])
    if not frames:
        raise ValueError("Agent context does not contain any frames")
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


def recent_dialogue(context: Dict[str, Any]) -> str:
    history = context.get("conversation_history", [])
    if not history:
        return "- 无"
    return "\n".join(
        f"- {entry.get('role', 'unknown')}: {entry.get('text', '')}"
        for entry in history[-6:]
    )


def latest_result_summary(context: Dict[str, Any]) -> str:
    latest_result = context.get("latest_result")
    if not latest_result:
        return "无"
    return (
        f"behavior={latest_result.get('behavior')}, "
        f"target_id={latest_result.get('target_id')}, "
        f"found={latest_result.get('found')}, "
        f"text={latest_result.get('text')}"
    )


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


def ensure_session_dirs(artifacts_root: Path, session_id: str) -> Dict[str, Path]:
    session_root = artifacts_root / session_id
    paths = {
        "session_root": session_root,
        "artifacts_dir": session_root / "agent_artifacts",
        "crops_dir": session_root / "reference_crops",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def detection_records(detections: List[Dict[str, Any]]) -> List[DetectionRecord]:
    return [
        DetectionRecord(
            track_id=int(detection["track_id"]),
            bbox=[int(value) for value in detection["bbox"]],
            score=float(detection.get("score", 1.0)),
        )
        for detection in detections
    ]


def build_rewrite_memory_input(
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
    if behavior == "init":
        return [str(current_frame_path)]

    if not latest_confirmed_frame_path:
        return [str(current_frame_path)]

    previous_frame_path = Path(str(latest_confirmed_frame_path))
    if previous_frame_path == current_frame_path:
        return [str(current_frame_path)]
    return [str(previous_frame_path), str(current_frame_path)]


def execute_reply_tool(context: Dict[str, Any], arguments: Dict[str, Any]) -> Dict[str, Any]:
    text = str(arguments.get("text", "")).strip()
    if not text:
        raise ValueError("reply tool requires a non-empty text argument")

    latest_result = context.get("latest_result") or {}
    latest_frame_payload = context.get("frames", [])[-1] if context.get("frames") else None
    clarification_question = optional_text(arguments.get("clarification_question"))
    needs_clarification = bool(arguments.get("needs_clarification", clarification_question is not None))
    pending_question = clarification_question if needs_clarification else None

    return {
        "behavior": "reply",
        "text": text,
        "frame_id": latest_result.get("frame_id")
        or (None if latest_frame_payload is None else str(latest_frame_payload.get("frame_id", "")) or None),
        "target_id": context.get("latest_target_id"),
        "found": bool(arguments.get("found", latest_result.get("found", False))),
        "needs_clarification": needs_clarification,
        "clarification_question": clarification_question,
        "memory": str(context.get("memory", "")),
        "pending_question": pending_question,
    }


def execute_select_tool(
    *,
    behavior: str,
    context: Dict[str, Any],
    arguments: Dict[str, Any],
    env_file: Path,
    config_path: Path,
    artifacts_root: Path,
) -> Dict[str, Any]:
    if behavior not in {"init", "track"}:
        raise ValueError(f"Unsupported select behavior: {behavior}")

    settings = load_settings(env_file)
    config = load_agent_config(config_path)
    frame = latest_frame(context)
    frame_path = Path(str(frame["image_path"]))
    detections = detection_records(frame.get("detections", []))
    session_dirs = ensure_session_dirs(artifacts_root, str(context["session_id"]))
    overlay_path = session_dirs["artifacts_dir"] / f"{frame['frame_id']}_overlay.jpg"
    save_detection_visualization(frame_path, detections, overlay_path)

    if behavior == "init":
        target_description = str(arguments.get("target_description", "")).strip()
        if not target_description:
            raise ValueError("init tool requires target_description")
        instruction = str(config["prompts"]["init_skill_prompt"]).format(
            target_description=target_description,
            candidates=candidate_summary(frame.get("detections", [])),
        )
        image_paths = [overlay_path]
        output_contract = config["contracts"]["select_init_target"]
    else:
        if not session_has_active_target(context):
            raise ValueError("track tool requires an active target in the session context")
        historical_frame_path = Path(str(context["latest_confirmed_frame_path"]))
        if not historical_frame_path.exists():
            raise ValueError(f"Missing latest_confirmed_frame_path: {historical_frame_path}")
        user_text = str(arguments.get("user_text", "")).strip() or "持续跟踪"
        instruction = str(config["prompts"]["track_skill_prompt"]).format(
            memory=str(context.get("memory", "")) or "无",
            latest_target_id=context.get("latest_target_id"),
            candidates=candidate_summary(frame.get("detections", [])),
            user_text=user_text,
            recent_dialogue=recent_dialogue(context),
        )
        image_paths = [historical_frame_path, overlay_path]
        output_contract = config["contracts"]["select_track_target"]

    output = call_model(
        api_key=settings.api_key,
        base_url=settings.base_url,
        timeout_seconds=settings.timeout_seconds,
        model=settings.main_model,
        instruction=instruction,
        image_paths=image_paths,
        output_contract=output_contract,
        max_tokens=int(config["limits"]["select_max_tokens"]),
    )
    normalized = normalize_select_result(parse_json_block(output["response_text"]))

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
        "memory": str(context.get("memory", "")),
        "reason": normalized["reason"],
        "latest_target_crop": None if crop_path is None else str(crop_path),
        "target_description": (
            str(arguments.get("target_description", "")).strip()
            if behavior == "init"
            else str(context.get("target_description", ""))
        ),
        "pending_question": normalized["clarification_question"],
        "rewrite_memory_input": rewrite_memory_input,
        "elapsed_seconds": output["elapsed_seconds"],
        "latest_result_summary": latest_result_summary(context),
    }


def execute_rewrite_memory_tool(
    *,
    arguments: Dict[str, Any],
    env_file: Path,
    config_path: Path,
) -> Dict[str, Any]:
    task = str(arguments.get("task", "")).strip()
    if task not in {"init", "update"}:
        raise ValueError("rewrite_memory tool requires task to be init or update")
    crop_path_value = str(arguments.get("crop_path", "")).strip()
    if not crop_path_value:
        raise ValueError("rewrite_memory tool requires crop_path")
    crop_path = Path(crop_path_value)
    frame_paths = [Path(str(path)) for path in arguments.get("frame_paths", [])]
    if not frame_paths:
        raise ValueError("rewrite_memory tool requires at least one frame path")

    settings = load_settings(env_file)
    config = load_agent_config(config_path)
    prompt_key = "memory_init_prompt" if task == "init" else "memory_optimize_prompt"
    output = call_model(
        api_key=settings.api_key,
        base_url=settings.base_url,
        timeout_seconds=settings.timeout_seconds,
        model=settings.sub_model,
        instruction=config["prompts"][prompt_key],
        image_paths=[crop_path, *frame_paths],
        output_contract=config["contracts"]["memory_markdown"],
        max_tokens=int(config["limits"]["memory_max_tokens"]),
    )
    memory = normalize_memory_markdown(output["response_text"])
    return {
        "task": task,
        "memory": memory,
        "frame_id": str(arguments.get("frame_id", "")),
        "target_id": int(arguments["target_id"]),
        "crop_path": str(crop_path),
        "elapsed_seconds": output["elapsed_seconds"],
    }


def describe_tools(tools_path: Path) -> Dict[str, Any]:
    manifest = load_json_path(tools_path)
    manifest["skill_root"] = str(SKILL_ROOT)
    manifest["default_config_path"] = str(DEFAULT_CONFIG_PATH)
    return manifest


def execute_tool(
    *,
    tool_name: str,
    context: Dict[str, Any],
    arguments: Dict[str, Any],
    env_file: Path,
    config_path: Path,
    artifacts_root: Path,
) -> Dict[str, Any]:
    if tool_name == "reply":
        return execute_reply_tool(context, arguments)
    if tool_name == "init":
        return execute_select_tool(
            behavior="init",
            context=context,
            arguments=arguments,
            env_file=env_file,
            config_path=config_path,
            artifacts_root=artifacts_root,
        )
    if tool_name == "track":
        return execute_select_tool(
            behavior="track",
            context=context,
            arguments=arguments,
            env_file=env_file,
            config_path=config_path,
            artifacts_root=artifacts_root,
        )
    if tool_name == "rewrite_memory":
        return execute_rewrite_memory_tool(
            arguments=arguments,
            env_file=env_file,
            config_path=config_path,
        )
    raise ValueError(f"Unsupported tool: {tool_name}")


def main() -> int:
    args = parse_args()
    if args.command == "describe":
        payload = describe_tools(Path(args.tools_path))
    else:
        context = read_json_input(args.context_file)
        payload = execute_tool(
            tool_name=args.tool,
            context=context,
            arguments=load_arguments(args.arguments_json, args.arguments_file),
            env_file=Path(args.env_file),
            config_path=Path(args.config_path),
            artifacts_root=Path(args.artifacts_root),
        )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
