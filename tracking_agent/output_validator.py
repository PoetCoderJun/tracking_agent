from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple


def _normalize_bbox(raw_bbox: Any) -> Optional[List[int]]:
    if raw_bbox is None:
        return None
    if not isinstance(raw_bbox, list) or len(raw_bbox) != 4:
        raise ValueError(f"bbox must be a list of four numbers, got: {raw_bbox!r}")
    try:
        return [int(value) for value in raw_bbox]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"bbox values must be numeric, got: {raw_bbox!r}") from exc


def denormalize_bbox_from_1000_scale(
    raw_bbox: Sequence[int],
    image_size: Tuple[int, int],
) -> List[int]:
    if len(raw_bbox) != 4:
        raise ValueError(f"bbox must contain four values, got: {raw_bbox!r}")

    width, height = image_size
    if width <= 0 or height <= 0:
        raise ValueError(f"image_size must be positive, got: {image_size!r}")

    x1, y1, x2, y2 = [int(value) for value in raw_bbox]
    # Qwen 3.5 usually returns 0..1000 coordinates, but in practice it can drift
    # slightly outside range. Clamp before denormalizing so tracking can continue.
    x1 = max(0, min(1000, x1))
    y1 = max(0, min(1000, y1))
    x2 = max(0, min(1000, x2))
    y2 = max(0, min(1000, y2))

    left = round(x1 / 1000 * width)
    top = round(y1 / 1000 * height)
    right = round(x2 / 1000 * width)
    bottom = round(y2 / 1000 * height)

    left = max(0, min(width - 1, left))
    top = max(0, min(height - 1, top))
    right = max(left + 1, min(width, right))
    bottom = max(top + 1, min(height, bottom))
    return [left, top, right, bottom]


def _normalize_bounding_box_id(raw_value: Any) -> Optional[int]:
    if raw_value in (None, ""):
        return None
    try:
        return int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"bounding_box_id must be numeric, got: {raw_value!r}") from exc


def validate_locate_result(result: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(result, dict):
        raise ValueError(f"Locate result must be a dict, got: {type(result)!r}")

    if "found" not in result or "reason" not in result:
        raise ValueError(f"Locate result missing required keys: {result!r}")

    found = bool(result["found"])
    bounding_box_id = _normalize_bounding_box_id(result.get("bounding_box_id"))
    if found and bounding_box_id is None:
        raise ValueError("Locate result returned found=true but bounding_box_id=null")
    if not found:
        bounding_box_id = None

    needs_clarification = bool(result.get("needs_clarification", False))
    clarification_question = result.get("clarification_question")
    if clarification_question is not None:
        clarification_question = str(clarification_question).strip() or None
    if needs_clarification and not clarification_question:
        clarification_question = "Please clarify which candidate should be tracked."

    return {
        "found": found,
        "bounding_box_id": bounding_box_id,
        "target_id": bounding_box_id,
        "reason": str(result["reason"]).strip(),
        "needs_clarification": needs_clarification,
        "clarification_question": clarification_question,
    }
