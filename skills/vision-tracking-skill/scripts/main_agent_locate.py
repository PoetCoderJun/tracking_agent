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

from agent_common import call_model, load_agent_config, parse_json_block

SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = SKILL_ROOT / "references" / "agent-config.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the skill main-agent locate call.")
    parser.add_argument("--task", choices=("init", "track"), required=True)
    parser.add_argument("--env-file", default=".ENV")
    parser.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--image-path", action="append", required=True)
    parser.add_argument("--target-description", default=None)
    parser.add_argument("--memory", default="")
    parser.add_argument("--clarification-note", action="append", default=[])
    return parser.parse_args()


def _build_track_instruction(config: dict[str, object], memory: str, notes: list[str]) -> str:
    prompt = str(config["prompts"]["track_skill_prompt"]).format(memory=memory)
    if not notes:
        return prompt
    note_block = "\n".join(f"- {note}" for note in notes if note.strip())
    if not note_block:
        return prompt
    return f"{prompt}\n\n用户补充澄清：\n{note_block}"


def main() -> int:
    args = parse_args()
    settings = load_settings(Path(args.env_file))
    config = load_agent_config(Path(args.config_path))
    image_paths = [Path(path) for path in args.image_path]

    if args.task == "init":
        if args.target_description is None:
            raise ValueError("--target-description is required for init")
        instruction = config["prompts"]["init_skill_prompt"].format(target_description=args.target_description)
        max_tokens = int(config["limits"]["main_max_tokens"])
    else:
        instruction = _build_track_instruction(config, args.memory, args.clarification_note)
        max_tokens = int(config["limits"]["track_max_tokens"])

    output = call_model(
        api_key=settings.api_key,
        base_url=settings.base_url,
        timeout_seconds=settings.timeout_seconds,
        model=settings.main_model,
        instruction=instruction,
        image_paths=image_paths,
        output_contract=config["contracts"]["main_locate"],
        max_tokens=max_tokens,
    )
    payload = {
        "task": args.task,
        "elapsed_seconds": output["elapsed_seconds"],
        "response_text": output["response_text"],
        "response_payload": output["response_payload"],
        "result": parse_json_block(output["response_text"]),
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
