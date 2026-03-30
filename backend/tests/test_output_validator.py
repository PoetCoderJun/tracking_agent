from __future__ import annotations

import pytest

from skills.tracking.output_validator import validate_locate_result


def test_validate_locate_result_accepts_bounding_box_id() -> None:
    normalized = validate_locate_result(
        {
            "found": True,
            "bounding_box_id": 12,
            "reason": "matched stable appearance",
            "needs_clarification": False,
        }
    )

    assert normalized["found"] is True
    assert normalized["bounding_box_id"] == 12
    assert normalized["target_id"] == 12


def test_validate_locate_result_rejects_target_id_alias() -> None:
    with pytest.raises(ValueError, match="bounding_box_id=null"):
        validate_locate_result(
            {
                "found": True,
                "target_id": 15,
                "reason": "matched stable appearance",
                "needs_clarification": False,
            }
        )


def test_validate_locate_result_rejects_found_without_id() -> None:
    with pytest.raises(ValueError, match="bounding_box_id=null"):
        validate_locate_result(
            {
                "found": True,
                "reason": "missing selection",
                "needs_clarification": False,
            }
        )
