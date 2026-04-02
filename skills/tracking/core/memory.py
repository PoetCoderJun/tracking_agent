from __future__ import annotations

import json
from typing import Any, Dict


DEFAULT_MEMORY_TEXT = "等待根据最新确认画面继续补充目标特征，并说明和周围人的区分点。"
MEMORY_KEYS = (
    "core",
    "front_view",
    "back_view",
    "distinguish",
)
PRIMARY_MEMORY_KEYS = (
    "core",
    "front_view",
    "back_view",
)
MEMORY_LABELS = {
    "core": "核心特征",
    "front_view": "正面特征",
    "back_view": "背面特征",
    "distinguish": "区分点",
}


def empty_tracking_memory() -> Dict[str, Any]:
    return {key: "" for key in MEMORY_KEYS}


def _normalized_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_field_text(value: Any) -> str:
    text = _normalized_text(value)
    if not text:
        return ""

    stripped = text.strip("。；;，,、 \n\t")
    empty_placeholders = {
        "无其他行人",
        "没有其他行人",
        "无明显混淆人物",
        "没有明显混淆人物",
        "当前无人",
        "当前场景无人",
        "当前场景无其他人",
        "当前画面无其他人",
    }
    if stripped in empty_placeholders:
        return ""
    return text


def _extract_text_from_string(memory_text: str) -> str:
    content_lines = []
    for line in memory_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        if stripped.startswith("```"):
            continue
        content_lines.append(stripped)

    content = " ".join(content_lines).strip()
    return content or memory_text.strip()


def _parse_memory_object(memory_value: Any) -> Dict[str, Any] | None:
    if isinstance(memory_value, dict):
        return memory_value
    if not isinstance(memory_value, str):
        return None

    stripped = memory_value.strip()
    if not stripped:
        return None

    candidates = [stripped]
    left = stripped.find("{")
    right = stripped.rfind("}")
    if left != -1 and right != -1 and right > left:
        candidates.append(stripped[left : right + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _normalize_raw_memory(memory_value: Any, parsed: Dict[str, Any] | None = None) -> Dict[str, Any]:
    normalized = empty_tracking_memory()
    parsed = parsed if isinstance(parsed, dict) else _parse_memory_object(memory_value)
    if parsed is not None:
        if any(key in parsed for key in PRIMARY_MEMORY_KEYS):
            normalized["core"] = _normalize_field_text(parsed.get("core"))
            normalized["front_view"] = _normalize_field_text(parsed.get("front_view"))
            normalized["back_view"] = _normalize_field_text(parsed.get("back_view"))
            normalized["distinguish"] = _normalize_field_text(parsed.get("distinguish"))
            return normalized

        appearance = parsed.get("appearance")
        summary = _normalized_text(parsed.get("summary"))
        legacy_parts = []
        if isinstance(appearance, dict):
            legacy_parts = [
                _normalized_text(appearance.get("head_face")),
                _normalized_text(appearance.get("upper_body")),
                _normalized_text(appearance.get("lower_body")),
                _normalized_text(appearance.get("shoes")),
                _normalized_text(appearance.get("accessories")),
                _normalized_text(appearance.get("body_shape")),
            ]
        detail = "；".join(part for part in legacy_parts if part)
        normalized["core"] = summary if summary and summary != DEFAULT_MEMORY_TEXT else detail
        normalized["front_view"] = detail
        normalized["back_view"] = ""
        normalized["distinguish"] = _normalize_field_text(parsed.get("distinguish"))
        return normalized

    text = _extract_text_from_string(_normalized_text(memory_value))
    if text:
        normalized["core"] = text
    return normalized


def _compose_summary(memory_payload: Dict[str, Any]) -> str:
    core = _normalized_text(memory_payload.get("core"))
    if core:
        return core
    front = _normalized_text(memory_payload.get("front_view"))
    if front:
        return front
    back = _normalized_text(memory_payload.get("back_view"))
    if back:
        return back
    return DEFAULT_MEMORY_TEXT


def normalize_tracking_memory(
    memory_value: Any,
    *,
    previous_memory: Any | None = None,
) -> Dict[str, Any]:
    base = empty_tracking_memory() if previous_memory is None else _normalize_raw_memory(previous_memory)
    current_parsed = _parse_memory_object(memory_value)
    current = _normalize_raw_memory(memory_value, current_parsed)
    current_keys = set() if current_parsed is None else {str(key) for key in current_parsed.keys()}

    for key in ("core", "front_view", "back_view"):
        value = _normalize_field_text(current.get(key))
        if value:
            base[key] = value
    distinguish = _normalize_field_text(current.get("distinguish"))
    if "distinguish" in current_keys:
        base["distinguish"] = distinguish
    elif distinguish:
        base["distinguish"] = distinguish
    return base


def tracking_memory_summary(memory_value: Any) -> str:
    return _compose_summary(normalize_tracking_memory(memory_value))


def tracking_memory_prompt_text(memory_value: Any) -> str:
    return json.dumps(
        normalize_tracking_memory(memory_value),
        ensure_ascii=False,
        indent=2,
    )


def tracking_memory_display_text(memory_value: Any) -> str:
    payload = normalize_tracking_memory(memory_value)
    lines = []
    for key in ("core", "front_view", "back_view"):
        value = _normalized_text(payload.get(key))
        if not value:
            continue
        lines.append(f"{MEMORY_LABELS[key]}：{value}")
    distinguish = _normalized_text(payload.get("distinguish"))
    if distinguish:
        lines.append(f"{MEMORY_LABELS['distinguish']}：{distinguish}")
    return "\n".join(lines)


def tracking_memory_flash_prompt_text(memory_value: Any) -> str:
    payload = normalize_tracking_memory(memory_value)
    sections = tracking_memory_sections(payload)
    lines = [
        "强特征清单：",
        f"- core: {sections['core'] or '(unknown)'}",
        f"- front_view: {sections['front_view'] or '(unknown)'}",
        f"- back_view: {sections['back_view'] or '(unknown)'}",
        f"- distinguish: {sections['distinguish'] or '(unknown)'}",
        "强冲突规则：",
        "- 如果当前候选出现与 memory 明显冲突的稳定特征，例如短裤变长裤、卡其短裤变深色短裤/长裤、白鞋变深色鞋、无眼镜变为清晰无眼镜、无帽子变有帽子，应优先判为 conflict。",
        "- 当前图里看不见的特征只能写 unknown，不能当作 match，也不能当作 conflict。",
        "- 机器人低机位或 crop 裁切时，上半身 Logo、眼镜、脸部细节经常看不全；如果这些部位没有被清楚拍到，只能写 unknown，不要写成“缺失”。",
    ]
    return "\n".join(lines)


def tracking_memory_sections(memory_value: Any) -> Dict[str, str]:
    payload = normalize_tracking_memory(memory_value)
    sections = {key: _normalized_text(payload.get(key)) for key in ("core", "front_view", "back_view")}
    sections["distinguish"] = _normalized_text(payload.get("distinguish"))
    return sections


def memory_history_key(memory_value: Any) -> str:
    return json.dumps(normalize_tracking_memory(memory_value), ensure_ascii=False, sort_keys=True)
