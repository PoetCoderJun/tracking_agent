from __future__ import annotations

import json
from pathlib import Path

from backend.skills import build_viewer_modules, installed_skill_names, project_skill_paths


ROOT = Path(__file__).resolve().parents[2]


def test_installed_skill_names_include_pluggable_skills() -> None:
    names = set(installed_skill_names())
    assert "tracking" in names
    assert "web_search" in names
    assert "feishu" in names


def test_build_viewer_modules_ignores_skills_without_viewer_hooks(tmp_path: Path) -> None:
    modules = build_viewer_modules(
        session={"session_id": "sess_001", "skill_cache": {}, "conversation_history": [], "result_history": []},
        state_root=tmp_path,
        perception_snapshot={"stream_status": {}},
        recent_frames=[],
    )
    assert "web_search" not in modules
    assert "feishu" not in modules


def test_web_search_turn_reports_missing_api_key(tmp_path: Path, capsys) -> None:
    from skills.web_search.scripts import search_turn

    turn_context_path = tmp_path / "turn_context.json"
    route_context_path = tmp_path / "route_context.json"
    route_context_path.write_text(
        json.dumps({"latest_user_text": "搜索今天的机器人新闻"}, ensure_ascii=True),
        encoding="utf-8",
    )
    turn_context_path.write_text(
        json.dumps(
            {
                "context_paths": {"route_context_path": str(route_context_path)},
                "env_file": str(tmp_path / ".ENV"),
                "artifacts_root": str(tmp_path / "artifacts"),
            },
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )

    exit_code = search_turn.main(
        [
            "--turn-context-file",
            str(turn_context_path),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["skill_name"] == "web_search"
    assert payload["tool"] == "search"
    assert "missing TAVILY_API_KEY" in payload["session_result"]["text"]


def test_feishu_notify_turn_writes_mock_outbox(tmp_path: Path, capsys) -> None:
    from skills.feishu.scripts import notify_turn

    turn_context_path = tmp_path / "turn_context.json"
    route_context_path = tmp_path / "route_context.json"
    route_context_path.write_text(
        json.dumps({"latest_user_text": "系统事件：charging_completed。请通知飞书"}, ensure_ascii=True),
        encoding="utf-8",
    )
    turn_context_path.write_text(
        json.dumps(
            {
                "session_id": "sess_notify",
                "context_paths": {"route_context_path": str(route_context_path)},
            },
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )

    exit_code = notify_turn.main(
        [
            "--turn-context-file",
            str(turn_context_path),
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
    outbox_path = tmp_path / "artifacts" / "feishu" / "mock_outbox.jsonl"
    entries = [json.loads(line) for line in outbox_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(entries) == 1
    assert entries[0]["title"] == "充电完成"


def test_feishu_notify_turn_sends_real_message_when_configured(tmp_path: Path, capsys, monkeypatch) -> None:
    from skills.feishu.scripts import notify_turn

    turn_context_path = tmp_path / "turn_context.json"
    route_context_path = tmp_path / "route_context.json"
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
    route_context_path.write_text(
        json.dumps({"latest_user_text": "系统事件：charging_completed。请通知飞书"}, ensure_ascii=True),
        encoding="utf-8",
    )
    turn_context_path.write_text(
        json.dumps(
            {
                "session_id": "sess_notify",
                "context_paths": {"route_context_path": str(route_context_path)},
                "env_file": str(env_path),
                "artifacts_root": str(tmp_path / "artifacts"),
            },
            ensure_ascii=True,
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

    monkeypatch.setattr(notify_turn.urllib.request, "urlopen", _fake_urlopen)

    exit_code = notify_turn.main(
        [
            "--turn-context-file",
            str(turn_context_path),
            "--title",
            "充电完成",
            "--message",
            "充电完成\n机器人底座充电已完成，请安排下一步。",
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
