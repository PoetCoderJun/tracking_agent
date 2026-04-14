from __future__ import annotations

import argparse
import json
import re
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from agent.infra.config import parse_dotenv
from agent.infra.paths import resolve_project_path
from agent.protocol.payloads import processed_skill_payload, reply_session_result
from agent.state.active import resolve_session_id
from agent.state.session import AgentSession, AgentSessionStore

FEISHU_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
FEISHU_SEND_URL = "https://open.feishu.cn/open-apis/im/v1/messages"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_message(session: AgentSession) -> str:
    latest_user_text = session.latest_user_text
    latest_result_text = str((session.latest_result or {}).get("text", "")).strip()
    if latest_user_text and latest_result_text:
        return f"{latest_user_text}\n\n最近结果：{latest_result_text}"
    return latest_user_text or latest_result_text


def _default_title(message: str, event_type: str) -> str:
    cleaned_event_type = str(event_type).strip()
    if cleaned_event_type:
        return f"系统事件：{cleaned_event_type}"
    message_line = str(message).strip().splitlines()[0] if str(message).strip() else ""
    if not message_line:
        return "飞书提醒"
    return message_line[:36]


def _load_feishu_config(env_file: Optional[Path]) -> Dict[str, str]:
    if env_file is None:
        return {}
    values = parse_dotenv(env_file)
    return {
        "app_id": str(values.get("FEISHU_APP_ID", "")).strip(),
        "app_secret": str(values.get("FEISHU_APP_SECRET", "")).strip(),
        "receive_id": str(values.get("FEISHU_NOTIFY_RECEIVE_ID", "")).strip(),
        "receive_id_type": str(values.get("FEISHU_NOTIFY_RECEIVE_ID_TYPE", "chat_id")).strip() or "chat_id",
    }


def _outbox_path(artifacts_root: Path) -> Path:
    return artifacts_root / "feishu" / "mock_outbox.jsonl"


def _write_outbox_entry(path: Path, entry: Dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=True))
        handle.write("\n")
    return path


def _fetch_tenant_access_token(*, app_id: str, app_secret: str) -> str:
    payload = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode("utf-8")
    request = urllib.request.Request(
        FEISHU_TOKEN_URL,
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8", errors="replace")
    parsed = json.loads(body)
    if int(parsed.get("code", 0)) != 0:
        raise RuntimeError(str(parsed.get("msg") or parsed))
    token = str(parsed.get("tenant_access_token", "")).strip()
    if not token:
        raise RuntimeError("missing tenant_access_token in Feishu auth response")
    return token


def _send_feishu_text_message(
    *,
    tenant_access_token: str,
    receive_id: str,
    receive_id_type: str,
    title: str,
    message: str,
) -> Dict[str, Any]:
    cleaned_message = re.sub(r"\s+\n", "\n", message).strip()
    if title and cleaned_message.startswith(f"{title}\n"):
        cleaned_message = cleaned_message[len(title) + 1 :].lstrip()
    if title and cleaned_message.startswith(f"{title}\r\n"):
        cleaned_message = cleaned_message[len(title) + 2 :].lstrip()
    text = f"{title}\n{cleaned_message}".strip() if cleaned_message else title
    payload = json.dumps(
        {
            "receive_id": receive_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{FEISHU_SEND_URL}?receive_id_type={receive_id_type}",
        data=payload,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {tenant_access_token}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8", errors="replace")
    parsed = json.loads(body)
    if int(parsed.get("code", 0)) != 0:
        raise RuntimeError(str(parsed.get("msg") or parsed))
    return dict(parsed.get("data") or {})


def build_feishu_payload(
    *,
    entry: Dict[str, Any],
    outbox_path: Path,
    request_id: str | None = None,
    request_function: str | None = None,
) -> Dict[str, Any]:
    title = str(entry.get("title", "")).strip()
    text = str(entry.get("message", "")).strip()
    mode = str(entry.get("mode", "")).strip()
    result_text = f"已发送飞书提醒：{title}" if mode == "real" else f"已发送飞书提醒（mock）：{title}"
    if text:
        result_text += f"\n{text}"
    session_result = {
        **reply_session_result(result_text, summary=f"feishu notify: {title}"),
    }
    if request_id not in (None, ""):
        session_result["request_id"] = str(request_id).strip()
    if request_function not in (None, ""):
        session_result["function"] = str(request_function).strip()
    return processed_skill_payload(
        skill_name="feishu",
        session_result=session_result,
        tool="notify",
        tool_output={**entry, "outbox_path": str(outbox_path)},
        latest_result_patch={
            "notification_channel": "feishu",
            "notification_event_type": entry.get("event_type"),
            "notification_title": title,
            "notification_sent_at": entry.get("sent_at"),
            "notification_outbox_path": str(outbox_path),
        },
        skill_state_patch={
            "last_message_id": entry.get("message_id"),
            "last_event_type": entry.get("event_type"),
        },
    )


def run_notify_turn(
    *,
    session_id: str | None,
    state_root: Path,
    title: str | None,
    message: str | None,
    event_type: str,
    recipient: str | None,
    recipient_type: str | None,
    env_file: Path,
    artifacts_root: Path,
    bound_session: AgentSession | None = None,
    request_id: str | None = None,
    stale_guard: Callable[[str], None] | None = None,
) -> Dict[str, Any]:
    session = bound_session
    if session is None:
        resolved_session_id = resolve_session_id(state_root=state_root, session_id=session_id)
        if resolved_session_id is None:
            raise ValueError("No active session found. Pass --session-id or create one first.")
        session = AgentSessionStore(state_root=state_root).load(resolved_session_id)

    request_function = str(session.session.get("latest_request_function") or "chat").strip()
    resolved_message = str(message or _default_message(session)).strip()
    resolved_event_type = str(event_type).strip()
    resolved_title = str(title or _default_title(resolved_message, resolved_event_type)).strip()
    config = _load_feishu_config(env_file)

    receive_id = str(recipient or config.get("receive_id") or "").strip()
    receive_id_type = str(recipient_type or config.get("receive_id_type") or "chat_id").strip() or "chat_id"
    configured = bool(config.get("app_id") and config.get("app_secret") and receive_id)

    sent_entry: Dict[str, Any]
    if configured:
        if stale_guard is not None:
            stale_guard("before_feishu_send")
        tenant_access_token = _fetch_tenant_access_token(app_id=config["app_id"], app_secret=config["app_secret"])
        send_data = _send_feishu_text_message(
            tenant_access_token=tenant_access_token,
            receive_id=receive_id,
            receive_id_type=receive_id_type,
            title=resolved_title,
            message=resolved_message,
        )
        sent_entry = {
            "message_id": str(send_data.get("message_id", "")).strip() or f"feishu_real_{uuid.uuid4().hex[:12]}",
            "title": resolved_title,
            "message": re.sub(r"\s+\n", "\n", resolved_message),
            "event_type": resolved_event_type or None,
            "recipient": receive_id,
            "recipient_type": receive_id_type,
            "sent_at": _utc_now(),
            "mode": "real",
            "configured": True,
            "feishu_app_id_present": True,
            "feishu_app_secret_present": True,
            "feishu_response": send_data,
        }
    else:
        missing = []
        if not config.get("app_id"):
            missing.append("FEISHU_APP_ID")
        if not config.get("app_secret"):
            missing.append("FEISHU_APP_SECRET")
        if not receive_id:
            missing.append("FEISHU_NOTIFY_RECEIVE_ID")
        sent_entry = {
            "message_id": f"feishu_mock_{uuid.uuid4().hex[:12]}",
            "title": resolved_title,
            "message": re.sub(r"\s+\n", "\n", resolved_message),
            "event_type": resolved_event_type or None,
            "recipient": receive_id or None,
            "recipient_type": receive_id_type,
            "sent_at": _utc_now(),
            "mode": "mock",
            "configured": False,
            "missing": missing,
        }

    if stale_guard is not None:
        stale_guard("before_feishu_outbox")
    outbox_path = _write_outbox_entry(_outbox_path(artifacts_root), sent_entry)
    return build_feishu_payload(
        entry=sent_entry,
        outbox_path=outbox_path,
        request_id=request_id,
        request_function=request_function,
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Write one Feishu notification turn from persisted session state.")
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--state-root", default="./.runtime/agent-runtime")
    parser.add_argument("--title", default=None)
    parser.add_argument("--message", default=None)
    parser.add_argument("--event-type", default="")
    parser.add_argument("--recipient", default=None)
    parser.add_argument("--recipient-type", default=None)
    parser.add_argument("--env-file", default=".ENV")
    parser.add_argument("--artifacts-root", default="./.runtime/pi-agent")
    args = parser.parse_args(argv)

    payload = run_notify_turn(
        session_id=args.session_id,
        state_root=resolve_project_path(args.state_root),
        title=args.title,
        message=args.message,
        event_type=str(args.event_type),
        recipient=args.recipient,
        recipient_type=args.recipient_type,
        env_file=resolve_project_path(args.env_file),
        artifacts_root=resolve_project_path(args.artifacts_root),
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
