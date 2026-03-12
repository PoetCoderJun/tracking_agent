from __future__ import annotations

import base64
import json
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict


def load_agent_config(config_path: Path) -> Dict[str, Any]:
    return json.loads(config_path.read_text(encoding="utf-8"))


def encode_image(path: Path) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def extract_text(response_payload: Dict[str, Any]) -> str:
    choices = response_payload.get("choices", [])
    if not choices:
        return json.dumps(response_payload, ensure_ascii=False)
    content = choices[0].get("message", {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(item.get("text", "") for item in content if item.get("type") == "text").strip()
    return str(content)


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
    }


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
