from __future__ import annotations

import json
from pathlib import Path

from tracking_agent.dashscope_client import (
    build_locate_request_payload,
    parse_bbox_response_content,
)
from tracking_agent.inference_runner import run_query_plan_inference


def _write_fake_jpeg(path: Path) -> None:
    path.write_bytes(b"\xff\xd8\xff\xe0" + b"fake-jpeg-data",)


def test_build_locate_request_payload_includes_images_and_target_description(
    tmp_path: Path,
) -> None:
    frame_paths = []
    for index in range(4):
        path = tmp_path / f"frame_{index}.jpg"
        _write_fake_jpeg(path)
        frame_paths.append(path)

    payload = build_locate_request_payload(
        model="qwen-vl-max-latest",
        target_description="穿深色上衣、向左走的人",
        frame_paths=frame_paths,
    )

    assert payload["model"] == "qwen-vl-max-latest"
    assert payload["temperature"] == 0
    content = payload["messages"][0]["content"]
    assert "穿深色上衣、向左走的人" in content[0]["text"]
    assert len([item for item in content if item["type"] == "image_url"]) == 4
    assert content[-1]["type"] == "text"
    assert "bbox" in content[-1]["text"]


def test_parse_bbox_response_content_handles_code_fenced_json() -> None:
    content = """```json
{"found": true, "bbox": [10, 20, 30, 40], "confidence": 0.91, "reason": "matched target"}
```"""

    parsed = parse_bbox_response_content(content)

    assert parsed["found"] is True
    assert parsed["bbox"] == [10, 20, 30, 40]
    assert parsed["confidence"] == 0.91


def test_run_query_plan_inference_writes_results(tmp_path: Path) -> None:
    frame_paths = []
    for index in range(8):
        path = tmp_path / f"frame_{index}.jpg"
        _write_fake_jpeg(path)
        frame_paths.append(path)

    query_plan_path = tmp_path / "query_plan.json"
    query_plan_path.write_text(
        json.dumps(
            {
                "query_interval_seconds": 5,
                "recent_frame_count": 4,
                "batches": [
                    {
                        "batch_index": 0,
                        "query_time_seconds": 0.0,
                        "frames": [
                            {
                                "index": 0,
                                "timestamp_seconds": 0.0,
                                "path": str(frame_paths[0]),
                            }
                        ],
                    },
                    {
                        "batch_index": 1,
                        "query_time_seconds": 5.0,
                        "frames": [
                            {
                                "index": 1,
                                "timestamp_seconds": 1.0,
                                "path": str(frame_paths[1]),
                            },
                            {
                                "index": 2,
                                "timestamp_seconds": 2.0,
                                "path": str(frame_paths[2]),
                            },
                            {
                                "index": 3,
                                "timestamp_seconds": 3.0,
                                "path": str(frame_paths[3]),
                            },
                        ],
                    },
                    {
                        "batch_index": 2,
                        "query_time_seconds": 10.0,
                        "frames": [
                            {
                                "index": 4,
                                "timestamp_seconds": 4.0,
                                "path": str(frame_paths[4]),
                            },
                            {
                                "index": 5,
                                "timestamp_seconds": 5.0,
                                "path": str(frame_paths[5]),
                            },
                            {
                                "index": 6,
                                "timestamp_seconds": 6.0,
                                "path": str(frame_paths[6]),
                            },
                            {
                                "index": 7,
                                "timestamp_seconds": 7.0,
                                "path": str(frame_paths[7]),
                            },
                        ],
                    },
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    class FakeDashScopeClient:
        def locate_target(self, target_description: str, frame_paths):
            newest = Path(frame_paths[-1]).name
            return {
                "found": newest == "frame_3.jpg",
                "bbox": [1, 2, 3, 4] if newest == "frame_3.jpg" else None,
                "confidence": 0.88 if newest == "frame_3.jpg" else 0.2,
                "reason": f"checked {newest} for {target_description}",
            }

    results_path = run_query_plan_inference(
        query_plan_path=query_plan_path,
        target_description="我要找的人",
        output_path=tmp_path / "bbox_results.json",
        client=FakeDashScopeClient(),
    )

    payload = json.loads(results_path.read_text(encoding="utf-8"))
    assert payload["target_description"] == "我要找的人"
    assert len(payload["results"]) == 3
    assert payload["results"][0]["result"]["found"] is False
    assert payload["results"][1]["result"]["found"] is True
    assert payload["results"][2]["result"]["found"] is False
