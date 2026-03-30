#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import load_settings
from backend.llm_client import call_model
from skills.tracking.memory_format import normalize_memory_markdown


SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = SKILL_ROOT / "references" / "robot-agent-config.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rewrite tracking memory from one successful tracking result.")
    parser.add_argument("--memory-file", required=True)
    parser.add_argument("--task", choices=("init", "update"), required=True)
    parser.add_argument("--crop-path", required=True)
    parser.add_argument("--frame-path", action="append", dest="frame_paths", default=[])
    parser.add_argument("--frame-id", required=True)
    parser.add_argument("--target-id", type=int, required=True)
    parser.add_argument("--env-file", default=".ENV")
    return parser.parse_args()


def load_agent_config(config_path: Path = DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    return json.loads(config_path.read_text(encoding="utf-8"))


def _load_previous_memory(memory_file: Path) -> str:
    if not memory_file.exists():
        return ""
    payload = json.loads(memory_file.read_text(encoding="utf-8"))
    tracking_state = dict(((payload.get("skill_cache") or {}).get("tracking") or {}))
    return str(tracking_state.get("latest_memory", "")).strip()


def execute_rewrite_memory_tool(
    *,
    memory_file: Path,
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
    prompt_key = "memory_init_prompt" if task == "init" else "memory_optimize_prompt"
    prompt = str(config["prompts"][prompt_key]).format(current_memory=_load_previous_memory(memory_file) or "(空)")
    output = call_model(
        api_key=settings.api_key,
        base_url=settings.base_url,
        timeout_seconds=settings.timeout_seconds,
        model=settings.sub_model,
        instruction=prompt,
        image_paths=[crop_path, *frame_paths],
        output_contract=config["contracts"]["memory_markdown"],
        max_tokens=int(config["limits"]["memory_max_tokens"]),
    )
    return {
        "task": task,
        "memory": normalize_memory_markdown(output["response_text"]),
        "frame_id": str(arguments.get("frame_id", "")),
        "target_id": int(arguments["target_id"]),
        "crop_path": str(crop_path),
        "elapsed_seconds": output["elapsed_seconds"],
    }


def main() -> int:
    args = parse_args()
    payload = execute_rewrite_memory_tool(
        memory_file=Path(args.memory_file),
        arguments={
            "task": args.task,
            "crop_path": args.crop_path,
            "frame_paths": list(args.frame_paths),
            "frame_id": args.frame_id,
            "target_id": int(args.target_id),
        },
        env_file=Path(args.env_file),
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
