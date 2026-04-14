from __future__ import annotations

from capabilities.tracking.policy.prompt_templates import (
    CONTINUOUS_TRACKING_SELECT_PROMPT_PATH,
    TRACKING_INIT_SELECT_PROMPT_PATH,
    TRACKING_RUNTIME_CONFIG_PATH,
    load_tracking_runtime_config,
)
from capabilities.tracking.policy.select import enforce_conservative_track_decision


def test_enforce_conservative_track_decision_downgrades_overlapping_target_box() -> None:
    normalized = {
        "found": True,
        "target_id": 2,
        "bounding_box_id": 2,
        "text": "已锁定目标 ID 2。",
        "reason": "外观一致。",
        "reject_reason": "",
        "needs_clarification": False,
        "clarification_question": None,
        "decision": "track",
        "candidate_checks": [],
    }
    detections = [
        {"track_id": 2, "bbox": [100, 100, 220, 400], "score": 0.9},
        {"track_id": 5, "bbox": [180, 120, 260, 390], "score": 0.8},
    ]

    result = enforce_conservative_track_decision(
        normalized=normalized,
        detections=[],
    )
    assert result["decision"] == "track"

    from capabilities.tracking.policy.select import detection_records

    result = enforce_conservative_track_decision(
        normalized=normalized,
        detections=detection_records(detections),
    )

    assert result["decision"] == "wait"
    assert result["found"] is False
    assert "重叠" in result["reject_reason"]


def test_tracking_prompt_ownership_and_runtime_config_are_separated() -> None:
    config = load_tracking_runtime_config()

    assert TRACKING_INIT_SELECT_PROMPT_PATH.exists()
    assert CONTINUOUS_TRACKING_SELECT_PROMPT_PATH.exists()
    assert TRACKING_RUNTIME_CONFIG_PATH.exists()
    assert "skills/tracking-init/" in str(TRACKING_INIT_SELECT_PROMPT_PATH)
    assert "capabilities/tracking/" in str(CONTINUOUS_TRACKING_SELECT_PROMPT_PATH)
    assert "capabilities/tracking/" in str(TRACKING_RUNTIME_CONFIG_PATH)
    assert "prompt_files" not in config
    assert "tracking_init_select_result" in config["contracts"]
    assert "continuous_tracking_select_result" in config["contracts"]
