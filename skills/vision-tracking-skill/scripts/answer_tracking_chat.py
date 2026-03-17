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

from agent_common import call_model, load_agent_config

SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = SKILL_ROOT / "references" / "agent-config.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Answer a tracking-related chat turn within an active session.")
    parser.add_argument("--question", required=True)
    parser.add_argument("--memory", required=True)
    parser.add_argument("--env-file", default=".ENV")
    parser.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--image-path", action="append", default=[])
    parser.add_argument("--note", action="append", default=[])
    return parser.parse_args()


def _build_instruction(config: dict[str, object], question: str, memory: str, notes: list[str]) -> str:
    prompt = str(config["prompts"]["answer_chat"]).format(question=question, memory=memory)
    if not notes:
        return prompt
    note_block = "\n".join(f"- {note}" for note in notes if note.strip())
    if not note_block:
        return prompt
    return f"{prompt}\n\n补充说明：\n{note_block}"


def main() -> int:
    args = parse_args()
    settings = load_settings(Path(args.env_file))
    config = load_agent_config(Path(args.config_path))
    image_paths = [Path(path) for path in args.image_path]
    output = call_model(
        api_key=settings.api_key,
        base_url=settings.base_url,
        timeout_seconds=settings.timeout_seconds,
        model=settings.chat_model,
        instruction=_build_instruction(config, args.question, args.memory, args.note),
        image_paths=image_paths,
        output_contract="只返回简短自然语言回答，不要返回 JSON，不要使用 ``` 代码块围栏。",
        max_tokens=int(config["limits"]["chat_max_tokens"]),
    )
    payload = {
        "elapsed_seconds": output["elapsed_seconds"],
        "response_text": output["response_text"],
        "response_payload": output["response_payload"],
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
