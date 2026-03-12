#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tracking_agent.config import load_settings
from tracking_agent.detection_visualization import save_detection_visualization
from tracking_agent.output_validator import validate_locate_result

from agent_common import call_model, load_agent_config, parse_json_block

SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = SKILL_ROOT / "references" / "agent-config.json"


@dataclass(frozen=True)
class DetectionRecord:
    track_id: int
    bbox: list[int]
    score: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the skill main-agent locate call.")
    parser.add_argument("--task", choices=("init", "track"), required=True)
    parser.add_argument("--env-file", default=".ENV")
    parser.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--image-path", action="append", required=True)
    parser.add_argument("--detections-json", required=True)
    parser.add_argument("--target-description", default=None)
    parser.add_argument("--memory", default="")
    parser.add_argument("--latest-bounding-box-id", type=int, default=None)
    parser.add_argument("--clarification-note", action="append", default=[])
    return parser.parse_args()


def parse_detections(raw_value: str) -> list[DetectionRecord]:
    payload = json.loads(raw_value)
    if not isinstance(payload, list):
        raise ValueError("--detections-json must decode to a list of detections")

    detections: list[DetectionRecord] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError(f"Detection must be an object, got: {item!r}")
        detections.append(
            DetectionRecord(
                track_id=int(item["track_id"]),
                bbox=[int(value) for value in item["bbox"]],
                score=float(item.get("score", 1.0)),
            )
        )
    return detections


def candidate_summary(detections: list[DetectionRecord]) -> str:
    if not detections:
        return "- 无候选人"
    return "\n".join(
        f"- bounding_box_id={int(detection.track_id)}: bbox={list(detection.bbox)}, score={float(detection.score):.2f}"
        for detection in detections
    )


def _build_track_instruction(
    config: dict[str, object],
    memory: str,
    notes: list[str],
    candidates: str,
    latest_bounding_box_id: int | None,
) -> str:
    prompt = str(config["prompts"]["track_skill_prompt"]).format(
        memory=memory or "无",
        candidates=candidates,
        latest_bounding_box_id=latest_bounding_box_id,
    )
    note_block = "\n".join(f"- {note}" for note in notes if note.strip())
    if not note_block:
        return prompt
    return f"{prompt}\n\n用户补充澄清：\n{note_block}"


def main() -> int:
    args = parse_args()
    settings = load_settings(Path(args.env_file))
    config = load_agent_config(Path(args.config_path))
    image_paths = [Path(path) for path in args.image_path]
    detections = parse_detections(args.detections_json)
    current_frame_path = image_paths[-1]

    with tempfile.TemporaryDirectory(prefix="tracking-locate-") as tmp_dir:
        overlay_path = Path(tmp_dir) / f"{current_frame_path.stem}_overlay.jpg"
        save_detection_visualization(
            image_path=current_frame_path,
            detections=detections,
            output_path=overlay_path,
        )

        if args.task == "init":
            if args.target_description is None:
                raise ValueError("--target-description is required for init")
            instruction = config["prompts"]["init_skill_prompt"].format(
                target_description=args.target_description,
                candidates=candidate_summary(detections),
            )
            model_image_paths = [overlay_path]
            max_tokens = int(config["limits"]["main_max_tokens"])
        else:
            instruction = _build_track_instruction(
                config=config,
                memory=args.memory,
                notes=args.clarification_note,
                candidates=candidate_summary(detections),
                latest_bounding_box_id=args.latest_bounding_box_id,
            )
            model_image_paths = [*image_paths[:-1], overlay_path]
            max_tokens = int(config["limits"]["track_max_tokens"])

        output = call_model(
            api_key=settings.api_key,
            base_url=settings.base_url,
            timeout_seconds=settings.timeout_seconds,
            model=settings.main_model,
            instruction=instruction,
            image_paths=model_image_paths,
            output_contract=config["contracts"]["main_locate"],
            max_tokens=max_tokens,
        )

    result = validate_locate_result(parse_json_block(output["response_text"]))
    payload = {
        "task": args.task,
        "elapsed_seconds": output["elapsed_seconds"],
        "response_text": output["response_text"],
        "response_payload": output["response_payload"],
        "result": result,
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
