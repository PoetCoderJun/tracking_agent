from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Optional

from agent.config import load_settings
from capabilities.llm_client import call_model
from world.perception.service import LocalPerceptionService
from agent.session_store import resolve_session_id
from agent.project_paths import resolve_project_path
from agent.session import AgentSession, AgentSessionStore
from agent.skill_payload import processed_skill_payload, reply_session_result


def _resolved_image_path(
    *,
    image_path: str,
    state_root: Path,
    session_id: str | None,
) -> Optional[Path]:
    explicit = str(image_path or "").strip()
    if explicit:
        candidate = Path(explicit)
        if candidate.exists() and candidate.is_file():
            return candidate
        return None

    resolved_session_id = resolve_session_id(state_root=state_root, session_id=session_id)
    if resolved_session_id is None:
        return None
    latest_frame = LocalPerceptionService(state_root=state_root).read_latest_frame()
    if not isinstance(latest_frame, dict):
        return None
    candidate = Path(str(latest_frame.get("image_path", "")).strip())
    if candidate.exists() and candidate.is_file():
        return candidate
    return None


def _instruction(user_text: str) -> str:
    return (
        "你是一个只做当前图片描述的视觉助手。\n"
        "请只根据当前图片回答，不要猜测图片里没有明确看到的内容。\n"
        "如果不确定，就明确说看不清或不能确定。\n"
        "用中文回答，先说明确能看到的内容，再补充少量不确定项。\n"
        f"用户问题：{user_text or '请描述当前画面'}"
    )


def _output_contract() -> str:
    return "只输出中文自然语言，不要输出 JSON，不要输出 Markdown 标题，不要解释规则。"


def build_describe_payload(
    *,
    text: str,
    tool_output: Dict[str, object],
    request_id: str | None = None,
    request_function: str | None = None,
) -> Dict[str, object]:
    session_result = {
        **reply_session_result(text),
    }
    if request_id not in (None, ""):
        session_result["request_id"] = str(request_id).strip()
    if request_function not in (None, ""):
        session_result["function"] = str(request_function).strip()
    return processed_skill_payload(
        skill_name="describe_image",
        session_result=session_result,
        tool="describe_image",
        tool_output=tool_output,
    )


def run_describe_turn(
    *,
    image_path: str,
    user_text: str,
    session_id: str | None,
    state_root: Path,
    env_file: Path,
    bound_session: AgentSession | None = None,
    request_id: str | None = None,
) -> Dict[str, object]:
    session = bound_session
    resolved_session_id = None if session is not None else resolve_session_id(state_root=state_root, session_id=session_id)
    if session is None and resolved_session_id is not None:
        session = AgentSessionStore(state_root=state_root).load(resolved_session_id)
    request_function = None if session is None else str(session.session.get("latest_request_function") or "chat").strip()
    resolved_image = _resolved_image_path(
        image_path=str(image_path),
        state_root=state_root,
        session_id=(session.session_id if session is not None else resolved_session_id),
    )
    if resolved_image is None:
        payload = build_describe_payload(
            text="我当前没有拿到可用的图片，暂时不能准确描述画面。",
            tool_output={"configured": False, "error": "missing image"},
            request_id=request_id,
            request_function=request_function,
        )
    else:
        settings = load_settings(env_file)
        output = call_model(
            api_key=settings.api_key,
            base_url=settings.base_url,
            timeout_seconds=settings.timeout_seconds,
            model=settings.model,
            instruction=_instruction(
                str(user_text).strip()
                or (session.latest_user_text if session is not None else "")
            ),
            image_paths=[resolved_image],
            output_contract=_output_contract(),
            max_tokens=400,
        )
        text = str(output.get("response_text", "")).strip() or "我暂时不能稳定描述这张图片。"
        payload = build_describe_payload(
            text=text,
            tool_output={
                "model": settings.model,
                "image_path": str(resolved_image),
                "elapsed_seconds": output.get("elapsed_seconds"),
            },
            request_id=request_id,
            request_function=request_function,
        )
    return payload


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run one deterministic image-description skill turn.")
    parser.add_argument("--image-path", default="")
    parser.add_argument("--user-text", default="")
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--state-root", default="./.runtime/agent-runtime")
    parser.add_argument("--env-file", default=".ENV")
    args = parser.parse_args(argv)

    payload = run_describe_turn(
        image_path=str(args.image_path),
        user_text=str(args.user_text),
        session_id=args.session_id,
        state_root=resolve_project_path(args.state_root),
        env_file=resolve_project_path(args.env_file),
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
