from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Optional

from backend.config import load_settings
from backend.llm_client import call_model
from backend.perception.service import LocalPerceptionService
from backend.persistence import resolve_session_id
from backend.project_paths import resolve_project_path
from backend.runtime_apply import apply_processed_payload
from backend.runtime_session import AgentSessionStore
from backend.skill_payload import processed_skill_payload, reply_session_result


def _resolved_image_path(
    *,
    image_path: str,
    state_root: Path,
    session_id: str | None,
    frame_buffer_size: int,
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
    latest_frame = LocalPerceptionService(
        state_root=state_root,
        frame_buffer_size=frame_buffer_size,
    ).read_latest_frame(resolved_session_id)
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


def build_describe_payload(*, text: str, tool_output: Dict[str, object]) -> Dict[str, object]:
    return processed_skill_payload(
        skill_name="describe_image",
        session_result=reply_session_result(text),
        tool="describe_image",
        tool_output=tool_output,
    )


def _latest_user_text(store: AgentSessionStore, session_id: str) -> str:
    session = store.load(session_id)
    history = list(session.session.get("conversation_history") or [])
    for entry in reversed(history):
        if str(entry.get("role", "")).strip() != "user":
            continue
        text = str(entry.get("text", "")).strip()
        if text:
            return text
    return ""


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run one deterministic image-description skill turn.")
    parser.add_argument("--image-path", default="")
    parser.add_argument("--user-text", default="")
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--state-root", default="./.runtime/agent-runtime")
    parser.add_argument("--frame-buffer-size", type=int, default=3)
    parser.add_argument("--env-file", default=".ENV")
    args = parser.parse_args(argv)

    state_root = resolve_project_path(args.state_root)
    resolved_session_id = resolve_session_id(state_root=state_root, session_id=args.session_id)
    sessions = AgentSessionStore(state_root=state_root, frame_buffer_size=int(args.frame_buffer_size))
    image_path = _resolved_image_path(
        image_path=str(args.image_path),
        state_root=state_root,
        session_id=resolved_session_id,
        frame_buffer_size=int(args.frame_buffer_size),
    )
    if image_path is None:
        payload = build_describe_payload(
            text="我当前没有拿到可用的图片，暂时不能准确描述画面。",
            tool_output={"configured": False, "error": "missing image"},
        )
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    settings = load_settings(resolve_project_path(args.env_file))
    output = call_model(
        api_key=settings.api_key,
        base_url=settings.base_url,
        timeout_seconds=settings.timeout_seconds,
        model=settings.model,
        instruction=_instruction(
            str(args.user_text).strip()
            or (
                _latest_user_text(sessions, resolved_session_id)
                if resolved_session_id is not None
                else ""
            )
        ),
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
    if resolved_session_id is not None:
        payload = apply_processed_payload(
            sessions=sessions,
            session_id=resolved_session_id,
            pi_payload=payload,
            env_file=resolve_project_path(args.env_file),
        )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
