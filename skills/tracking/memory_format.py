from __future__ import annotations

import json
from typing import Any, Dict


DEFAULT_MEMORY_TEXT = "等待根据最新确认画面继续补充目标特征，并说明和周围人的区分点。"
APPEARANCE_KEYS = (
    "head_face",
    "upper_body",
    "lower_body",
    "shoes",
    "accessories",
    "body_shape",
)
APPEARANCE_LABELS = {
    "head_face": "头脸",
    "upper_body": "上装",
    "lower_body": "下装",
    "shoes": "鞋子",
    "accessories": "配饰",
    "body_shape": "体型",
}


def empty_tracking_memory() -> Dict[str, Any]:
    return {
        "appearance": {key: "" for key in APPEARANCE_KEYS},
        "distinguish": "",
        "summary": DEFAULT_MEMORY_TEXT,
    }


def _normalized_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_distinguish_text(value: Any) -> str:
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


def _parsed_memory_object_keys(memory_value: Any) -> set[str]:
    parsed = _parse_memory_object(memory_value)
    if not isinstance(parsed, dict):
        return set()
    return {str(key) for key in parsed.keys()}


def _normalize_raw_memory(memory_value: Any) -> Dict[str, Any]:
    normalized = empty_tracking_memory()
    parsed = _parse_memory_object(memory_value)
    if parsed is not None:
        appearance = parsed.get("appearance")
        if isinstance(appearance, dict):
            for key in APPEARANCE_KEYS:
                normalized["appearance"][key] = _normalized_text(appearance.get(key))
        normalized["distinguish"] = _normalize_distinguish_text(parsed.get("distinguish"))
        normalized["summary"] = _normalized_text(parsed.get("summary"))
        return normalized

    text = _extract_text_from_string(_normalized_text(memory_value))
    if text:
        normalized["summary"] = text
    return normalized


def _compose_summary(memory_payload: Dict[str, Any]) -> str:
    parts = [
        _normalized_text(memory_payload.get("appearance", {}).get(key))
        for key in APPEARANCE_KEYS
    ]
    detail = "；".join(part for part in parts if part)
    distinguish = _normalized_text(memory_payload.get("distinguish"))
    if detail and distinguish:
        return f"{detail}。区分点：{distinguish}"
    if detail:
        return detail
    if distinguish:
        return f"区分点：{distinguish}"
    return DEFAULT_MEMORY_TEXT


def normalize_tracking_memory(
    memory_value: Any,
    *,
    previous_memory: Any | None = None,
) -> Dict[str, Any]:
    if previous_memory is None:
        base = empty_tracking_memory()
    else:
        base = _normalize_raw_memory(previous_memory)
    current = _normalize_raw_memory(memory_value)
    current_keys = _parsed_memory_object_keys(memory_value)

    for key in APPEARANCE_KEYS:
        value = _normalized_text(current["appearance"].get(key))
        if value:
            base["appearance"][key] = value
    distinguish = _normalize_distinguish_text(current.get("distinguish"))
    if "distinguish" in current_keys:
        base["distinguish"] = distinguish
    elif distinguish:
        base["distinguish"] = distinguish
    summary = _normalized_text(current.get("summary"))
    if summary and summary != DEFAULT_MEMORY_TEXT:
        base["summary"] = summary

    if not _normalized_text(base.get("summary")) or base["summary"] == DEFAULT_MEMORY_TEXT:
        base["summary"] = _compose_summary(base)
    return base


def tracking_memory_summary(memory_value: Any) -> str:
    return _normalized_text(normalize_tracking_memory(memory_value).get("summary")) or DEFAULT_MEMORY_TEXT


def tracking_memory_prompt_text(memory_value: Any) -> str:
    return json.dumps(
        normalize_tracking_memory(memory_value),
        ensure_ascii=False,
        indent=2,
    )


def tracking_memory_display_text(memory_value: Any) -> str:
    payload = normalize_tracking_memory(memory_value)
    lines = [f"摘要：{tracking_memory_summary(payload)}"]
    for key in APPEARANCE_KEYS:
        value = _normalized_text(payload["appearance"].get(key))
        if not value:
            continue
        lines.append(f"{APPEARANCE_LABELS[key]}：{value}")
    distinguish = _normalized_text(payload.get("distinguish"))
    if distinguish:
        lines.append(f"区分点：{distinguish}")
    return "\n".join(lines)


def tracking_memory_flash_prompt_text(memory_value: Any) -> str:
    payload = normalize_tracking_memory(memory_value)
    sections = tracking_memory_sections(payload)
    lines = [
        "强特征清单：",
        f"- summary: {sections['summary'] or DEFAULT_MEMORY_TEXT}",
        f"- head_face: {sections['head_face'] or '(unknown)'}",
        f"- upper_body: {sections['upper_body'] or '(unknown)'}",
        f"- lower_body: {sections['lower_body'] or '(unknown)'}",
        f"- shoes: {sections['shoes'] or '(unknown)'}",
        f"- accessories: {sections['accessories'] or '(unknown)'}",
        f"- body_shape: {sections['body_shape'] or '(unknown)'}",
        f"- distinguish: {sections['distinguish'] or '(unknown)'}",
        "强冲突规则：",
        "- 如果当前候选出现与 memory 明显冲突的稳定特征，例如短裤变长裤、卡其短裤变深色短裤/长裤、白鞋变深色鞋、无眼镜变为清晰无眼镜、无帽子变有帽子，应优先判为 conflict。",
        "- 当前图里看不见的特征只能写 unknown，不能当作 match。",
    ]
    return "\n".join(lines)


def tracking_memory_sections(memory_value: Any) -> Dict[str, str]:
    payload = normalize_tracking_memory(memory_value)
    sections = {key: _normalized_text(payload["appearance"].get(key)) for key in APPEARANCE_KEYS}
    sections["distinguish"] = _normalized_text(payload.get("distinguish"))
    sections["summary"] = tracking_memory_summary(payload)
    return sections


def memory_history_key(memory_value: Any) -> str:
    return json.dumps(normalize_tracking_memory(memory_value), ensure_ascii=False, sort_keys=True)
