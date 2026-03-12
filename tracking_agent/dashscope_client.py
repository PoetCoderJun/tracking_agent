from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Sequence

from tracking_agent.config import Settings


def encode_image_as_data_url(image_path: Path) -> str:
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def build_multimodal_request_payload(
    model: str,
    instruction: str,
    frame_paths: Sequence[Path],
    output_contract: str,
    temperature: float = 0,
    max_tokens: int = 300,
) -> Dict[str, Any]:
    if not frame_paths:
        raise ValueError("frame_paths must not be empty")

    content: List[Dict[str, Any]] = [{"type": "text", "text": instruction}]
    content.extend(
        {
            "type": "image_url",
            "image_url": {"url": encode_image_as_data_url(path)},
        }
        for path in frame_paths
    )
    content.append({"type": "text", "text": output_contract})
    return {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": content}],
    }


def build_locate_request_payload(
    model: str,
    target_description: str,
    frame_paths: Sequence[Path],
) -> Dict[str, Any]:
    instruction = (
        "你现在负责在一小段按时间顺序排列的图像序列中定位指定人物。"
        "这些帧从旧到新排序。"
        f'目标描述是：“{target_description}”。'
        "你需要综合所有帧理解目标的连续动作和去向，但最终只返回最新一帧中的 bounding box。"
        "如果你不能在最新一帧中有把握地找到该目标，请返回 found=false 且 bbox=null。"
    )
    output_contract = (
        "只返回合法 JSON，格式为："
        '{"found": true|false, "bbox": [x1, y1, x2, y2] | null, '
        '"confidence": 0.0, "reason": "简短解释"}。'
    )
    return build_multimodal_request_payload(
        model=model,
        instruction=instruction,
        frame_paths=frame_paths,
        output_contract=output_contract,
        temperature=0,
        max_tokens=300,
    )


def parse_bbox_response_content(content: Any) -> Dict[str, Any]:
    if isinstance(content, dict):
        parsed = content
        if "found" not in parsed or "confidence" not in parsed or "reason" not in parsed:
            raise ValueError(f"Missing required keys in model response: {parsed}")
        if parsed.get("found") and parsed.get("bbox") is None:
            raise ValueError("Model returned found=true with bbox=null")
        return parsed

    cleaned = content.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse model JSON response: {cleaned}") from exc

    if "found" not in parsed or "confidence" not in parsed or "reason" not in parsed:
        raise ValueError(f"Missing required keys in model response: {parsed}")
    if parsed.get("found") and parsed.get("bbox") is None:
        raise ValueError("Model returned found=true with bbox=null")
    return parsed


def extract_message_text(response_payload: Dict[str, Any]) -> str:
    choices = response_payload.get("choices", [])
    if not choices:
        raise ValueError(f"DashScope response did not include choices: {response_payload}")

    content = choices[0].get("message", {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if item.get("type") == "text":
                parts.append(item.get("text", ""))
        return "".join(parts).strip()
    raise ValueError(f"Unsupported response content type: {content!r}")


class DashScopeVisionClient:
    def __init__(self, settings: Settings):
        self._settings = settings

    def _post_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self._settings.api_key:
            raise ValueError("DASHSCOPE_API_KEY is required for live inference.")

        request = urllib.request.Request(
            url=f"{self._settings.base_url.rstrip('/')}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._settings.api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=self._settings.timeout_seconds,
            ) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"DashScope HTTP error {exc.code}: {body}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"DashScope request failed: {exc}") from exc

        return response_payload

    def complete_text(
        self,
        instruction: str,
        frame_paths: Sequence[Path],
        output_contract: str,
        temperature: float = 0,
        max_tokens: int = 700,
        model: str | None = None,
    ) -> str:
        payload = build_multimodal_request_payload(
            model=model or self._settings.model,
            instruction=instruction,
            frame_paths=frame_paths,
            output_contract=output_contract,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        response_payload = self._post_payload(payload)
        return extract_message_text(response_payload)

    def complete_json(
        self,
        instruction: str,
        frame_paths: Sequence[Path],
        output_contract: str,
        parser: Callable[[str], Dict[str, Any]],
        temperature: float = 0,
        max_tokens: int = 500,
        model: str | None = None,
    ) -> Dict[str, Any]:
        content = self.complete_text(
            instruction=instruction,
            frame_paths=frame_paths,
            output_contract=output_contract,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model,
        )
        return parser(content)

    def locate_target(
        self,
        target_description: str,
        frame_paths: Sequence[Path],
    ) -> Dict[str, Any]:
        payload = build_locate_request_payload(
            model=self._settings.model,
            target_description=target_description,
            frame_paths=frame_paths,
        )
        response_payload = self._post_payload(payload)
        content = extract_message_text(response_payload)
        return parse_bbox_response_content(content)
