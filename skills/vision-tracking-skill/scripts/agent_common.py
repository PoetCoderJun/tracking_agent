from __future__ import annotations

import base64
import json
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional


def load_agent_config(config_path: Path) -> Dict[str, Any]:
    return json.loads(config_path.read_text(encoding="utf-8"))


def encode_image(path: Path) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def extract_text(response_payload: Dict[str, Any]) -> str:
    choices = response_payload.get("choices", [])
    if not choices:
        return json.dumps(response_payload, ensure_ascii=False)
    content = choices[0].get("message", {}).get("content")
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(item.get("text", "") for item in content if item.get("type") == "text").strip()
    return str(content)


def extract_message(response_payload: Dict[str, Any]) -> Dict[str, Any]:
    choices = response_payload.get("choices", [])
    if not choices:
        return {}
    return choices[0].get("message", {}) or {}


def extract_tool_calls(response_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    message = extract_message(response_payload)
    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, list):
        return []
    return [tool_call for tool_call in tool_calls if isinstance(tool_call, dict)]


def _request_chat_completion(
    *,
    api_key: str,
    base_url: str,
    timeout_seconds: int,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    request = urllib.request.Request(
        url=f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        response_payload = json.loads(response.read().decode("utf-8"))
    return {
        "elapsed_seconds": time.perf_counter() - started,
        "response_payload": response_payload,
        "response_text": extract_text(response_payload),
        "response_message": extract_message(response_payload),
        "tool_calls": extract_tool_calls(response_payload),
    }


def call_model(
    api_key: str,
    base_url: str,
    timeout_seconds: int,
    model: str,
    instruction: str,
    image_paths: list[Path],
    output_contract: str,
    max_tokens: int,
) -> Dict[str, Any]:
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": max_tokens,
        "enable_thinking": False,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": instruction},
                    *[
                        {"type": "image_url", "image_url": {"url": encode_image(path)}}
                        for path in image_paths
                    ],
                    {"type": "text", "text": output_contract},
                ],
            }
        ],
    }
    return _request_chat_completion(
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        payload=payload,
    )


def call_model_with_tools(
    api_key: str,
    base_url: str,
    timeout_seconds: int,
    model: str,
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    max_tokens: int,
    tool_choice: Any = "auto",
    parallel_tool_calls: bool = False,
) -> Dict[str, Any]:
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": max_tokens,
        "enable_thinking": False,
        "messages": messages,
        "tools": tools,
        "tool_choice": tool_choice,
        "parallel_tool_calls": parallel_tool_calls,
    }
    return _request_chat_completion(
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        payload=payload,
    )


def parse_json_block(text: str) -> Dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return json.loads(cleaned)
