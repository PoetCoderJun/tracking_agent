from __future__ import annotations

import json

from backend.cli import main, parse_args


def test_parse_args_session_start(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "robot_agent.py",
            "session-start",
            "--state-root",
            "./.runtime/agent-runtime",
            "--fresh",
        ],
    )
    args = parse_args()
    assert args.command == "session-start"
    assert args.fresh is True


def test_parse_args_session_show(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "robot_agent.py",
            "session-show",
            "--session-id",
            "sess_001",
        ],
    )
    args = parse_args()
    assert args.command == "session-show"
    assert args.session_id == "sess_001"


def test_main_session_start_marks_active_session(monkeypatch, tmp_path, capsys) -> None:
    state_root = tmp_path / "state"
    monkeypatch.setattr(
        "sys.argv",
        [
            "robot_agent.py",
            "session-start",
            "--session-id",
            "sess_001",
            "--state-root",
            str(state_root),
            "--fresh",
        ],
    )

    assert main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "started"
    assert payload["session_id"] == "sess_001"
    active_session = json.loads((state_root / "active_session.json").read_text(encoding="utf-8"))
    assert active_session["session_id"] == "sess_001"


def test_main_session_start_without_session_id_creates_new_session(monkeypatch, tmp_path, capsys) -> None:
    state_root = tmp_path / "state"
    (state_root / "active_session.json").parent.mkdir(parents=True, exist_ok=True)
    (state_root / "active_session.json").write_text(
        json.dumps({"session_id": "sess_old", "updated_at": "2026-04-08T00:00:00+00:00"}, ensure_ascii=True),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "robot_agent.py",
            "session-start",
            "--state-root",
            str(state_root),
        ],
    )

    assert main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "started"
    assert payload["session_id"] != "sess_old"
    active_session = json.loads((state_root / "active_session.json").read_text(encoding="utf-8"))
    assert active_session["session_id"] == payload["session_id"]


def test_main_session_show_returns_state_paths(monkeypatch, tmp_path, capsys) -> None:
    state_root = tmp_path / "state"
    (state_root / "active_session.json").parent.mkdir(parents=True, exist_ok=True)
    (state_root / "active_session.json").write_text(
        json.dumps({"session_id": "sess_001", "updated_at": "2026-04-08T00:00:00+00:00"}, ensure_ascii=True),
        encoding="utf-8",
    )
    session_dir = state_root / "sessions" / "sess_001"
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "session.json").write_text(
        json.dumps(
            {
                "session_id": "sess_001",
                "device_id": "robot_01",
                "latest_request_id": None,
                "latest_request_function": None,
                "latest_result": None,
                "result_history": [],
                "conversation_history": [],
                "recent_frames": [],
                "user_preferences": {},
                "environment_map": {},
                "perception_cache": {},
                "skill_cache": {},
                "created_at": "2026-04-08T00:00:00+00:00",
                "updated_at": "2026-04-08T00:00:00+00:00",
            },
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "robot_agent.py",
            "session-show",
            "--state-root",
            str(state_root),
        ],
    )

    assert main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["session_id"] == "sess_001"
    assert payload["state_paths"]["session_path"].endswith("sessions/sess_001/session.json")


def test_main_tracking_init_calls_deterministic_backend(monkeypatch, tmp_path, capsys) -> None:
    state_root = tmp_path / "state"
    session_dir = state_root / "sessions" / "sess_001"
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "session.json").write_text(
        json.dumps(
            {
                "session_id": "sess_001",
                "device_id": "robot_01",
                "latest_request_id": None,
                "latest_request_function": None,
                "latest_result": None,
                "result_history": [],
                "conversation_history": [],
                "recent_frames": [],
                "user_preferences": {},
                "environment_map": {},
                "perception_cache": {},
                "skill_cache": {},
                "created_at": "2026-04-08T00:00:00+00:00",
                "updated_at": "2026-04-08T00:00:00+00:00",
            },
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )
    (state_root / "active_session.json").write_text(
        json.dumps({"session_id": "sess_001", "updated_at": "2026-04-08T00:00:00+00:00"}, ensure_ascii=True),
        encoding="utf-8",
    )

    captured = {}

    def fake_process_tracking_init_direct(**kwargs):
        captured.update(kwargs)
        return {"status": "processed", "tool": "init", "skill_name": "tracking"}

    monkeypatch.setattr("backend.cli.process_tracking_init_direct", fake_process_tracking_init_direct)
    monkeypatch.setattr(
        "sys.argv",
        [
            "robot_agent.py",
            "tracking-init",
            "--state-root",
            str(state_root),
            "--text",
            "开始跟踪穿黑衣服的人",
        ],
    )

    assert main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["tool"] == "init"
    assert captured["session_id"] == "sess_001"
