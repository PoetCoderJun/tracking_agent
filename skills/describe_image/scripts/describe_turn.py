from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.config import load_settings
from backend.llm_client import call_model
from backend.skill_payload import processed_skill_payload, reply_session_result


def _load_turn_context(turn_context_file: Path) -> Dict[str, Any]:
    return json.loads(turn_context_file.read_text(encoding="utf-8"))


def _route_context(turn_context: Dict[str, Any]) -> Dict[str, Any]:
    route_context_path = ((turn_context.get("context_paths") or {}).get("route_context_path"))
    if route_context_path in (None, ""):
        return {}
    return json.loads(Path(str(route_context_path)).read_text(encoding="utf-8"))


def _image_path(turn_context: Dict[str, Any]) -> Optional[Path]:
    route_context = _route_context(turn_context)
    latest_frame = route_context.get("latest_frame")
    if not isinstance(latest_frame, dict):
        return None
    image_path = str(latest_frame.get("image_path", "")).strip()
    if not image_path:
        return None
    candidate = Path(image_path)
    if candidate.exists() and candidate.is_file():
        return candidate
    return None


def _user_text(turn_context: Dict[str, Any]) -> str:
    route_context = _route_context(turn_context)
    return str(route_context.get("latest_user_text", "")).strip()


def _instruction(user_text: str) -> str:
    return (
        "你是一个只做当前图片描述的视觉助手。\n"
        "请只根据当前图片回答，不要猜测图片里没有明确看到的内容。\n"
        "如果不确定，就明确说看不清或不能确定。\n"
        "用中文回答，先说明确能看到的内容，再补充少量不确定项。\n"
        f"用户问题：{user_text or '请描述当前画面'}"
    )


def _output_contract() -> str:
    return (
        "只输出中文自然语言，不要输出 JSON，不要输出 Markdown 标题，不要解释规则。"
    )


def build_describe_payload(*, text: str, tool_output: Dict[str, Any]) -> Dict[str, Any]:
    return processed_skill_payload(
        skill_name="describe_image",
        session_result=reply_session_result(text),
        tool="describe_image",
        tool_output=tool_output,
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run one deterministic image-description skill turn.")
    parser.add_argument("--turn-context-file", required=True)
    parser.add_argument("--env-file", default=None)
    args = parser.parse_args(argv)

    turn_context = _load_turn_context(Path(args.turn_context_file))
    image_path = _image_path(turn_context)
    if image_path is None:
        payload = build_describe_payload(
            text="我当前没有拿到可用的图片，暂时不能准确描述画面。",
            tool_output={"configured": False, "error": "missing image"},
        )
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    env_file = Path(str(args.env_file)) if args.env_file not in (None, "") else Path(str(turn_context.get("env_file", ".ENV")))
    settings = load_settings(env_file)
    output = call_model(
        api_key=settings.api_key,
        base_url=settings.base_url,
        timeout_seconds=settings.timeout_seconds,
        model=settings.model,
        instruction=_instruction(_user_text(turn_context)),
        image_paths=[image_path],
        output_contract=_output_contract(),
        max_tokens=400,
    )
    text = str(output.get("response_text", "")).strip() or "我暂时不能稳定描述这张图片。"
    payload = build_describe_payload(
        text=text,
        tool_output={
            "model": settings.model,
            "image_path": str(image_path),
            "elapsed_seconds": output.get("elapsed_seconds"),
        },
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
