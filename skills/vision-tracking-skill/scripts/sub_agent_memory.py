#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tracking_agent.config import load_settings
from tracking_agent.memory_format import normalize_memory_markdown

from agent_common import call_model, load_agent_config

SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = SKILL_ROOT / "references" / "agent-config.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the skill sub-agent memory call.")
    parser.add_argument("--task", choices=("init", "update"), required=True)
    parser.add_argument("--env-file", default=".ENV")
    parser.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--image-path", action="append", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = load_settings(Path(args.env_file))
    config = load_agent_config(Path(args.config_path))
    image_paths = [Path(path) for path in args.image_path]
    prompt_key = "sub_init_memory" if args.task == "init" else "sub_update_memory"

    output = call_model(
        api_key=settings.api_key,
        base_url=settings.base_url,
        timeout_seconds=settings.timeout_seconds,
        model=settings.sub_model,
        instruction=config["prompts"][prompt_key],
        image_paths=image_paths,
        output_contract=config["contracts"]["memory_markdown"],
        max_tokens=int(config["limits"]["memory_max_tokens"]),
    )
    payload = {
        "task": args.task,
        "elapsed_seconds": output["elapsed_seconds"],
        "response_text": output["response_text"],
        "response_payload": output["response_payload"],
        "memory": normalize_memory_markdown(output["response_text"]),
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
