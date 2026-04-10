#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.config import load_settings
from capabilities.llm_client import call_model
from capabilities.tracking.memory import (
    empty_tracking_memory,
    normalize_tracking_memory,
    read_tracking_memory_snapshot,
    tracking_memory_prompt_text,
)


SKILL_TRACKING_ROOT = ROOT / "skills" / "tracking"
DEFAULT_CONFIG_PATH = SKILL_TRACKING_ROOT / "references" / "robot-agent-config.json"
REFERENCE_VIEW_ALIASES = {
    "front": "front",
    "front_view": "front",
    "frontview": "front",
    "正面": "front",
    "back": "back",
    "back_view": "back",
    "backview": "back",
    "背面": "back",
    "unknown": "unknown",
    "unk": "unknown",
    "侧面": "unknown",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rewrite tracking memory from one successful tracking result.")
    parser.add_argument("--session-file", required=True)
    parser.add_argument("--task", choices=("init", "update"), required=True)
    parser.add_argument("--crop-path", required=True)
    parser.add_argument("--frame-path", action="append", dest="frame_paths", default=[])
    parser.add_argument("--frame-id", required=True)
    parser.add_argument("--target-id", type=int, required=True)
    parser.add_argument("--confirmation-reason", default="")
    parser.add_argument("--candidate-checks-json", default="")
    parser.add_argument("--env-file", default=".ENV")
    return parser.parse_args()


def load_agent_config(config_path: Path = DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    return json.loads(config_path.read_text(encoding="utf-8"))


def _load_previous_memory(session_file: Path) -> Any:
    payload = json.loads(session_file.read_text(encoding="utf-8"))
    session_id = str(payload.get("session_id", "")).strip()
    if not session_id:
        return empty_tracking_memory()
    state_root = session_file.resolve().parents[2]
    snapshot = read_tracking_memory_snapshot(state_root=state_root, session_id=session_id)
    latest_memory = snapshot.get("memory", {})
    if latest_memory in (None, "", {}):
        return empty_tracking_memory()
    return normalize_tracking_memory(latest_memory)


def _normalize_reference_view(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return "unknown"
    return REFERENCE_VIEW_ALIASES.get(text, "unknown")


def _reference_view_from_response_text(response_text: str) -> str:
    stripped = response_text.strip()
    candidates = [stripped]
    left = stripped.find("{")
    right = stripped.rfind("}")
    if left != -1 and right != -1 and right > left:
        candidates.append(stripped[left : right + 1])

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return _normalize_reference_view(payload.get("reference_view"))
    return "unknown"


def _optional_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    return str(value).strip()


def _normalize_candidate_checks(value: Any) -> list[Dict[str, Any]]:
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError:
            return []
    if not isinstance(value, list):
        return []
    normalized: list[Dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        normalized.append(dict(item))
    return normalized


def _reference_view_goal_prompt_text(value: Any) -> str:
    goal = str(value or "").strip().lower()
    if goal == "front":
        return (
            "当前系统缺少可靠的正面锚点。"
            " 若当前 crop 清晰展示正面，请优先补齐 front_view，并将 reference_view 设为 front；"
            " 如果当前不是清晰正面，只能返回 unknown，不能为了补齐正面而脑补。"
        )
    if goal == "back":
        return (
            "当前系统缺少可靠的背面锚点。"
            " 若当前 crop 清晰展示背面，请优先补齐 back_view，并将 reference_view 设为 back；"
            " 如果当前不是清晰背面，只能返回 unknown，不能因为看不到正面就把背影视角判成 conflict。"
        )
    if goal == "any":
        return (
            "当前系统的正面/背面锚点尚未补齐。"
            " 如果当前 crop 清晰展示正面，就优先补齐 front；如果清晰展示背面，就优先补齐 back；"
            " 如果视角不明，只能返回 unknown。"
        )
    return ""


def _candidate_checks_prompt_text(candidate_checks: list[Dict[str, Any]]) -> str:
    if not candidate_checks:
        return "[]"
    return json.dumps(candidate_checks, ensure_ascii=False, indent=2)


def execute_rewrite_memory_tool(
    *,
    session_file: Path,
    arguments: Dict[str, Any],
    env_file: Path,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> Dict[str, Any]:
    task = str(arguments.get("task", "")).strip()
    if task not in {"init", "update"}:
        raise ValueError("rewrite_memory requires task to be init or update")

    crop_path = Path(str(arguments.get("crop_path", "")).strip())
    if not crop_path.exists():
        raise ValueError(f"Missing crop_path: {crop_path}")

    frame_paths = [Path(str(path)) for path in arguments.get("frame_paths", [])]
    if not frame_paths:
        raise ValueError("rewrite_memory requires at least one frame path")

    settings = load_settings(env_file)
    config = load_agent_config(config_path)
    previous_memory = _load_previous_memory(session_file)
    prompt_key = "memory_init_prompt" if task == "init" else "memory_optimize_prompt"
    confirmation_reason = _optional_text(arguments.get("confirmation_reason"))
    candidate_checks = _normalize_candidate_checks(arguments.get("candidate_checks"))
    reference_view_goal = _reference_view_goal_prompt_text(arguments.get("desired_reference_view"))
    prompt = str(config["prompts"][prompt_key]).format(
        current_memory=tracking_memory_prompt_text(previous_memory),
        confirmation_reason=confirmation_reason or "(none)",
        candidate_checks=_candidate_checks_prompt_text(candidate_checks),
    )
    if reference_view_goal:
        prompt = f"{reference_view_goal}\n\n{prompt}"
    output = call_model(
        api_key=settings.api_key,
        base_url=settings.base_url,
        timeout_seconds=settings.timeout_seconds,
        model=settings.sub_model,
        instruction=prompt,
        image_paths=[crop_path, *frame_paths],
        output_contract=config["contracts"]["memory_json"],
        max_tokens=int(config["limits"]["memory_max_tokens"]),
    )
    return {
        "task": task,
        "memory": normalize_tracking_memory(output["response_text"]),
        "frame_id": str(arguments.get("frame_id", "")),
        "target_id": int(arguments["target_id"]),
        "crop_path": str(crop_path),
        "reference_view": _reference_view_from_response_text(output["response_text"]),
        "elapsed_seconds": output["elapsed_seconds"],
    }


def main() -> int:
    args = parse_args()
    payload = execute_rewrite_memory_tool(
        session_file=Path(args.session_file),
        arguments={
            "task": args.task,
            "crop_path": args.crop_path,
            "frame_paths": list(args.frame_paths),
            "frame_id": args.frame_id,
            "target_id": int(args.target_id),
            "confirmation_reason": args.confirmation_reason,
            "candidate_checks": args.candidate_checks_json,
        },
        env_file=Path(args.env_file),
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
