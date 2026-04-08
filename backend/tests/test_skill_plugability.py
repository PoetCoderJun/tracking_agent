from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from backend.runtime_session import AgentSessionStore
from backend.skills import build_viewer_modules, installed_skill_names

ROOT = Path(__file__).resolve().parents[2]
WEB_SEARCH_SCRIPT = ROOT / "skills" / "web-search" / "scripts" / "search_turn.py"
DESCRIBE_IMAGE_SCRIPT = ROOT / "skills" / "describe-image" / "scripts" / "describe_turn.py"


def _load_script_module(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _start_session(tmp_path: Path, session_id: str, user_text: str = "") -> AgentSessionStore:
    store = AgentSessionStore(tmp_path / "state")
    store.start_fresh_session(session_id, device_id="robot_01")
    if user_text:
        store.append_chat_request(
            session_id=session_id,
            device_id="robot_01",
            text=user_text,
            request_id="req_001",
        )
    return store


def test_installed_skill_names_include_pluggable_skills() -> None:
    names = set(installed_skill_names())
    assert "tracking" in names
    assert "web-search" in names
    assert "feishu" in names
    assert "describe-image" in names


def test_build_viewer_modules_ignores_skills_without_viewer_hooks(tmp_path: Path) -> None:
    modules = build_viewer_modules(
        session={"session_id": "sess_001", "skill_cache": {}, "conversation_history": [], "result_history": []},
        state_root=tmp_path,
        perception_snapshot={"stream_status": {}},
        recent_frames=[],
    )
    assert "web-search" not in modules
    assert "feishu" not in modules


def test_web_search_turn_reports_missing_api_key(tmp_path: Path, capsys) -> None:
    search_turn = _load_script_module(WEB_SEARCH_SCRIPT, "test_web_search_turn")

    store = _start_session(tmp_path, "sess_search", user_text="搜索今天的机器人新闻")
    exit_code = search_turn.main(
        [
            "--session-id",
            "sess_search",
            "--state-root",
            str(store.state_root),
            "--env-file",
            str(tmp_path / ".ENV"),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["skill_name"] == "web_search"
    assert payload["tool"] == "search"
    assert "missing TAVILY_API_KEY" in payload["session_result"]["text"]
    assert "skill_state_patch" not in payload
    assert "rewrite_output" not in payload
    assert "rewrite_memory_input" not in payload


def test_web_search_turn_without_session_stays_stateless(tmp_path: Path, capsys) -> None:
    search_turn = _load_script_module(WEB_SEARCH_SCRIPT, "test_web_search_turn_stateless")

    env_path = tmp_path / ".ENV"
    env_path.write_text("", encoding="utf-8")
    exit_code = search_turn.main(
        [
            "--query",
            "搜索今天的机器人新闻",
            "--state-root",
            str(tmp_path / "state"),
            "--env-file",
            str(env_path),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["skill_name"] == "web_search"
    assert "missing TAVILY_API_KEY" in payload["session_result"]["text"]
    assert not ((tmp_path / "state") / "active_session.json").exists()


def test_feishu_notify_turn_requires_existing_or_explicit_session(tmp_path: Path) -> None:
    from skills.feishu.scripts import notify_turn

    env_path = tmp_path / ".ENV"
    env_path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="No active session found"):
        notify_turn.main(
            [
                "--state-root",
                str(tmp_path / "state"),
                "--env-file",
                str(env_path),
            ]
        )


def test_describe_image_turn_without_session_stays_stateless(tmp_path: Path, capsys) -> None:
    describe_turn = _load_script_module(DESCRIBE_IMAGE_SCRIPT, "test_describe_image_turn")

    env_path = tmp_path / ".ENV"
    env_path.write_text("", encoding="utf-8")
    exit_code = describe_turn.main(
        [
            "--state-root",
            str(tmp_path / "state"),
            "--env-file",
            str(env_path),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["skill_name"] == "describe_image"
    assert payload["tool_output"]["error"] == "missing image"
    assert not ((tmp_path / "state") / "active_session.json").exists()


def test_feishu_notify_turn_writes_mock_outbox(tmp_path: Path, capsys) -> None:
    from skills.feishu.scripts import notify_turn

    store = _start_session(tmp_path, "sess_notify", user_text="系统事件：charging_completed。请通知飞书")
    env_path = tmp_path / ".ENV"
    env_path.write_text("", encoding="utf-8")
    exit_code = notify_turn.main(
        [
            "--session-id",
            "sess_notify",
            "--state-root",
            str(store.state_root),
            "--env-file",
            str(env_path),
            "--title",
            "充电完成",
            "--message",
            "机器人底座充电已完成，请安排下一步。",
            "--event-type",
            "charging_completed",
            "--artifacts-root",
            str(tmp_path / "artifacts"),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["skill_name"] == "feishu"
    assert payload["tool"] == "notify"
    assert "rewrite_output" not in payload
    assert "rewrite_memory_input" not in payload
    outbox_path = tmp_path / "artifacts" / "feishu" / "mock_outbox.jsonl"
    entries = [json.loads(line) for line in outbox_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(entries) == 1
    assert entries[0]["title"] == "充电完成"


def test_feishu_notify_turn_sends_real_message_when_configured(tmp_path: Path, capsys, monkeypatch) -> None:
    from skills.feishu.scripts import notify_turn

    store = _start_session(tmp_path, "sess_notify", user_text="系统事件：charging_completed。请通知飞书")
    env_path = tmp_path / ".ENV"
    env_path.write_text(
        "\n".join(
            [
                "FEISHU_APP_ID=cli_app_id",
                "FEISHU_APP_SECRET=cli_app_secret",
                "FEISHU_NOTIFY_RECEIVE_ID=oc_demo_chat",
                "FEISHU_NOTIFY_RECEIVE_ID_TYPE=chat_id",
            ]
        ),
        encoding="utf-8",
    )

    class _Response:
        def __init__(self, payload: dict[str, object]):
            self._payload = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        def read(self) -> bytes:
            return self._payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    requests: list[tuple[str, dict[str, str], dict[str, object]]] = []

    def _fake_urlopen(request, timeout=0):
        body = json.loads(request.data.decode("utf-8")) if request.data else {}
        requests.append((request.full_url, dict(request.headers), body))
        if request.full_url.endswith("/tenant_access_token/internal"):
            return _Response({"code": 0, "tenant_access_token": "tenant_token_001"})
        return _Response({"code": 0, "data": {"message_id": "om_123"}})

    import backend.feishu as backend_feishu

    monkeypatch.setattr(backend_feishu.urllib.request, "urlopen", _fake_urlopen)

    exit_code = notify_turn.main(
        [
            "--session-id",
            "sess_notify",
            "--state-root",
            str(store.state_root),
            "--title",
            "充电完成",
            "--message",
            "充电完成\n机器人底座充电已完成，请安排下一步。",
            "--env-file",
            str(env_path),
            "--artifacts-root",
            str(tmp_path / "artifacts"),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["skill_name"] == "feishu"
    assert payload["tool"] == "notify"
    assert "已发送飞书提醒：充电完成" in payload["session_result"]["text"]
    sent_text = json.loads(str(requests[1][2]["content"]))["text"]
    assert sent_text == "充电完成\n机器人底座充电已完成，请安排下一步。"
    assert len(requests) == 2
    assert requests[0][2] == {"app_id": "cli_app_id", "app_secret": "cli_app_secret"}
    assert requests[1][2]["receive_id"] == "oc_demo_chat"
    outbox_path = tmp_path / "artifacts" / "feishu" / "mock_outbox.jsonl"
    entries = [json.loads(line) for line in outbox_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert entries[0]["mode"] == "real"
    assert entries[0]["message_id"] == "om_123"
