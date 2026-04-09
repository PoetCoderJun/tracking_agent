from __future__ import annotations

import json
from pathlib import Path

from backend.runtime_session import AgentSessionStore
from backend.tts import run_tts_turn


def test_run_tts_turn_writes_mock_outbox_and_updates_session(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    artifacts_root = tmp_path / "artifacts"
    store = AgentSessionStore(state_root)
    store.start_fresh_session("sess_tts", device_id="robot_01")

    payload = run_tts_turn(
        text="请注意安全。",
        session_id="sess_tts",
        state_root=state_root,
        env_file=tmp_path / ".ENV",
        artifacts_root=artifacts_root,
    )

    session = store.load("sess_tts")
    outbox_path = Path(str(payload["tool_output"]["outbox_path"]))
    lines = outbox_path.read_text(encoding="utf-8").strip().splitlines()

    assert payload["session_result"]["robot_response"]["action"] == "speak"
    assert payload["tool_output"]["mode"] == "mock"
    assert session.latest_result["robot_response"]["action"] == "speak"
    assert session.capabilities["tts"]["last_text"] == "请注意安全。"
    assert len(lines) == 1
    assert json.loads(lines[0])["text"] == "请注意安全。"


def test_run_tts_turn_defaults_to_latest_user_text(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    artifacts_root = tmp_path / "artifacts"
    store = AgentSessionStore(state_root)
    store.start_fresh_session("sess_tts_default", device_id="robot_01")
    store.append_chat_request(
        session_id="sess_tts_default",
        device_id="robot_01",
        text="请播报实验开始。",
        request_id="req_001",
    )

    payload = run_tts_turn(
        text="",
        session_id="sess_tts_default",
        state_root=state_root,
        env_file=tmp_path / ".ENV",
        artifacts_root=artifacts_root,
    )

    assert payload["session_result"]["robot_response"]["text"] == "请播报实验开始。"
    assert store.load("sess_tts_default").capabilities["tts"]["last_text"] == "请播报实验开始。"
