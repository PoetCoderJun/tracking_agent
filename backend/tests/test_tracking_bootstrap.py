from __future__ import annotations

from pathlib import Path

import pytest

import skills.tracking.bootstrap as bootstrap


def test_float_env_value_uses_default_for_blank_and_invalid_values() -> None:
    assert bootstrap.float_env_value({}, "QUERY_INTERVAL_SECONDS", 3.0) == 3.0
    assert (
        bootstrap.float_env_value({"QUERY_INTERVAL_SECONDS": "abc"}, "QUERY_INTERVAL_SECONDS", 3.0)
        == 3.0
    )
    assert (
        bootstrap.float_env_value({"QUERY_INTERVAL_SECONDS": "7.5"}, "QUERY_INTERVAL_SECONDS", 3.0)
        == 7.5
    )


def test_load_tracking_env_values_reads_resolved_env_file(tmp_path: Path) -> None:
    env_path = tmp_path / ".ENV"
    env_path.write_text("QUERY_INTERVAL_SECONDS=9\n", encoding="utf-8")

    values = bootstrap.load_tracking_env_values(env_path)

    assert values["QUERY_INTERVAL_SECONDS"] == "9"


def test_build_tracking_chat_command_targets_backend_cli_chat() -> None:
    command = bootstrap.build_tracking_chat_command(
        session_id="sess_001",
        text="继续跟踪",
        device_id="robot_01",
        state_root="./.runtime/agent-runtime",
        artifacts_root="./.runtime/pi-agent",
        env_file=".ENV",
        pi_binary="pi",
    )

    assert command[:4] == [bootstrap.sys.executable, "-m", "backend.cli", "chat"]
    assert command[-2:] == ["--skill", "tracking"]
    assert "--session-id" in command
    assert "sess_001" in command


def test_wait_for_first_tracking_frame_returns_resolved_session(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(bootstrap, "resolve_session_id", lambda **_: "sess_001")
    monkeypatch.setattr(bootstrap, "_session_has_frame", lambda *_: True)

    session_id = bootstrap.wait_for_first_tracking_frame(
        state_root=tmp_path,
        requested_session_id=None,
        timeout_seconds=1.0,
    )

    assert session_id == "sess_001"


def test_wait_for_first_tracking_frame_times_out(monkeypatch, tmp_path: Path) -> None:
    monotonic_values = iter([0.0, 0.6, 1.2])

    monkeypatch.setattr(bootstrap, "resolve_session_id", lambda **_: "sess_001")
    monkeypatch.setattr(bootstrap, "_session_has_frame", lambda *_: False)
    monkeypatch.setattr(bootstrap.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(bootstrap.time, "sleep", lambda *_: None)

    with pytest.raises(TimeoutError):
        bootstrap.wait_for_first_tracking_frame(
            state_root=tmp_path,
            requested_session_id="sess_001",
            timeout_seconds=1.0,
            poll_interval_seconds=0.1,
        )
