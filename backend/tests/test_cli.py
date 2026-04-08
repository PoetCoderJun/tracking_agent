import argparse
import json

import backend.cli as cli_module
from backend.cli import main, parse_args
from backend.project_paths import resolve_project_path


def test_parse_args_chat_interface(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "robot_agent.py",
            "chat",
            "--session-id",
            "sess_001",
            "--text",
            "继续跟踪",
        ],
    )

    args = parse_args()

    assert args.command == "chat"
    assert args.session_id == "sess_001"
    assert args.text == "继续跟踪"
    assert args.state_root == "./.runtime/agent-runtime"
    assert args.pi_binary == "pi"


def test_parse_args_chat_allows_active_session_mode(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "robot_agent.py",
            "chat",
            "--text",
            "继续跟踪",
        ],
    )

    args = parse_args()

    assert args.command == "chat"
    assert args.session_id is None
    assert args.text == "继续跟踪"


def test_parse_args_accepts_runtime_paths_for_chat(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "robot_agent.py",
            "chat",
            "--session-id",
            "sess_001",
            "--text",
            "请生成一段语音 hello",
            "--state-root",
            "./.runtime/custom-state",
            "--artifacts-root",
            "./.runtime/custom-artifacts",
        ],
    )

    args = parse_args()

    assert args.command == "chat"
    assert args.state_root == "./.runtime/custom-state"
    assert args.artifacts_root == "./.runtime/custom-artifacts"


def test_parse_args_start_interface(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "robot_agent.py",
            "start",
            "--session-id",
            "sess_001",
        ],
    )

    args = parse_args()

    assert args.command == "start"
    assert args.session_id == "sess_001"
    assert args.state_root == "./.runtime/agent-runtime"


def test_parse_args_event_interface(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "robot_agent.py",
            "event",
            "--session-id",
            "sess_001",
            "--event-type",
            "charging_completed",
            "--text",
            "机器人底座充电已完成，请决定是否通知飞书。",
        ],
    )

    args = parse_args()

    assert args.command == "event"
    assert args.session_id == "sess_001"
    assert args.event_type == "charging_completed"
    assert "通知飞书" in args.text


def test_parse_args_repl_interface(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "robot_agent.py",
            "repl",
            "--state-root",
            "./.runtime/agent-runtime",
        ],
    )

    args = parse_args()

    assert args.command == "repl"
    assert args.env_file == ".ENV"
    assert args.pi_binary == "pi"


def test_parse_args_tracking_track_interface(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "robot_agent.py",
            "tracking-track",
            "--session-id",
            "sess_001",
            "--text",
            "继续跟踪",
        ],
    )

    args = parse_args()

    assert args.command == "tracking-track"
    assert args.session_id == "sess_001"
    assert args.text == "继续跟踪"
    assert args.state_root == "./.runtime/agent-runtime"


def test_parse_args_tracking_init_interface(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "robot_agent.py",
            "tracking-init",
            "--session-id",
            "sess_001",
            "--text",
            "穿黑衣服的人",
        ],
    )

    args = parse_args()

    assert args.command == "tracking-init"
    assert args.session_id == "sess_001"
    assert args.text == "穿黑衣服的人"
    assert args.state_root == "./.runtime/agent-runtime"


def test_main_tracking_track_calls_backend_direct_path(monkeypatch, tmp_path, capsys) -> None:
    state_root = tmp_path / "state"
    session_dir = resolve_project_path(str(state_root)) / "sessions" / "sess_001"
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "session.json").write_text(
        json.dumps({"session_id": "sess_001", "device_id": "robot_01"}),
        encoding="utf-8",
    )
    (resolve_project_path(str(state_root)) / "active_session.json").write_text(
        json.dumps({"session_id": "sess_001"}, ensure_ascii=False),
        encoding="utf-8",
    )
    calls = []

    def fake_process_tracking_request_direct(**kwargs):
        calls.append(kwargs)
        return {
            "session_id": "sess_001",
            "status": "processed",
            "skill_name": "tracking",
            "session_result": {"behavior": "track", "text": "ok"},
            "latest_result_patch": None,
            "skill_state_patch": None,
            "user_preferences_patch": None,
            "environment_map_patch": None,
            "perception_cache_patch": None,
            "robot_response": {"action": "track", "text": "ok"},
            "tool": "track",
            "tool_output": {"behavior": "track"},
            "rewrite_output": None,
            "rewrite_memory_input": None,
            "latest_result": {"behavior": "track", "text": "ok"},
            "session": {"session_id": "sess_001"},
        }

    monkeypatch.setattr("backend.cli.process_tracking_request_direct", fake_process_tracking_request_direct)
    monkeypatch.setattr(
        "sys.argv",
        [
            "robot_agent.py",
            "tracking-track",
            "--session-id",
            "sess_001",
            "--state-root",
            str(state_root),
            "--text",
            "继续跟踪",
        ],
    )

    assert main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["tool"] == "track"
    assert len(calls) == 1


def test_main_tracking_init_calls_backend_direct_path(monkeypatch, tmp_path, capsys) -> None:
    state_root = tmp_path / "state"
    session_dir = resolve_project_path(str(state_root)) / "sessions" / "sess_001"
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "session.json").write_text(
        json.dumps({"session_id": "sess_001", "device_id": "robot_01"}),
        encoding="utf-8",
    )
    (resolve_project_path(str(state_root)) / "active_session.json").write_text(
        json.dumps({"session_id": "sess_001"}, ensure_ascii=False),
        encoding="utf-8",
    )
    calls = []

    def fake_process_tracking_init_direct(**kwargs):
        calls.append(kwargs)
        return {
            "session_id": "sess_001",
            "status": "processed",
            "skill_name": "tracking",
            "session_result": {"behavior": "init", "text": "ok"},
            "latest_result_patch": None,
            "skill_state_patch": None,
            "user_preferences_patch": None,
            "environment_map_patch": None,
            "perception_cache_patch": None,
            "robot_response": {"action": "track", "text": "ok"},
            "tool": "init",
            "tool_output": {"behavior": "init"},
            "rewrite_output": None,
            "rewrite_memory_input": None,
            "latest_result": {"behavior": "init", "text": "ok"},
            "session": {"session_id": "sess_001"},
        }

    monkeypatch.setattr("backend.cli.process_tracking_init_direct", fake_process_tracking_init_direct)
    monkeypatch.setattr(
        "sys.argv",
        [
            "robot_agent.py",
            "tracking-init",
            "--session-id",
            "sess_001",
            "--state-root",
            str(state_root),
            "--text",
            "穿黑衣服的人",
        ],
    )

    assert main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["tool"] == "init"
    assert len(calls) == 1


def test_main_start_persists_enabled_skills_and_active_session(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    state_root = tmp_path / "state"
    monkeypatch.setattr("backend.cli.available_project_skill_names", lambda: ["tracking", "web_search", "feishu"])
    monkeypatch.setattr(
        "sys.argv",
        [
            "robot_agent.py",
            "start",
            "--state-root",
            str(state_root),
        ],
    )

    assert main() == 0

    payload = json.loads(capsys.readouterr().out)
    session_id = payload["session_id"]
    session_payload = json.loads(
        (
            resolve_project_path(str(state_root))
            / "sessions"
            / session_id
            / "session.json"
        ).read_text(encoding="utf-8")
    )
    active_session = json.loads(
        (resolve_project_path(str(state_root)) / "active_session.json").read_text(encoding="utf-8")
    )

    assert payload["enabled_skills"] == ["tracking", "web_search", "feishu"]
    assert session_payload["environment_map"]["agent_runtime"]["enabled_skills"] == ["tracking", "web_search", "feishu"]
    assert active_session["session_id"] == session_id


def test_main_event_routes_through_runner(monkeypatch, tmp_path, capsys) -> None:
    state_root = tmp_path / "state"
    resolve_project_path(str(state_root)).mkdir(parents=True, exist_ok=True)
    (resolve_project_path(str(state_root)) / "active_session.json").write_text(
        json.dumps({"session_id": "sess_001", "updated_at": "2026-04-06T00:00:00+00:00"}, ensure_ascii=True),
        encoding="utf-8",
    )
    captured = {}

    class _FakeRunner:
        def process_chat_request(self, **kwargs):
            captured.update(kwargs)
            return {
                "status": "processed",
                "skill_name": "feishu",
                "session_result": {"behavior": "reply", "text": "已发送飞书提醒。"},
                "tool": "notify",
            }

    monkeypatch.setattr("backend.cli._runner_from_args", lambda _: _FakeRunner())
    monkeypatch.setattr(
        "sys.argv",
        [
            "robot_agent.py",
            "event",
            "--state-root",
            str(state_root),
            "--event-type",
            "charging_completed",
            "--text",
            "机器人底座充电已完成，请决定是否通知飞书。",
        ],
    )

    assert main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["skill_name"] == "feishu"
    assert captured["session_id"] == "sess_001"
    assert "系统事件：charging_completed" in captured["text"]


def test_main_repl_starts_session_and_launches_tui(monkeypatch, tmp_path) -> None:
    state_root = tmp_path / "state"
    artifacts_root = tmp_path / "artifacts"
    captured = {}

    def fake_launch_repl_tui(*, args, session_id, enabled_skills):
        captured["args"] = args
        captured["session_id"] = session_id
        captured["enabled_skills"] = enabled_skills
        return 0

    monkeypatch.setattr("backend.cli._launch_repl_tui", fake_launch_repl_tui)
    monkeypatch.setattr("backend.cli.available_project_skill_names", lambda: ["tracking", "web_search", "feishu"])
    monkeypatch.setattr(
        "sys.argv",
        [
            "robot_agent.py",
            "repl",
            "--session-id",
            "sess_repl_001",
            "--state-root",
            str(state_root),
            "--artifacts-root",
            str(artifacts_root),
        ],
    )

    assert main() == 0
    payload = json.loads((resolve_project_path(str(state_root)) / "sessions" / "sess_repl_001" / "session.json").read_text(encoding="utf-8"))
    assert payload["environment_map"].get("agent_runtime") in (None, {})
    assert (
        json.loads((resolve_project_path(str(state_root)) / "active_session.json").read_text(encoding="utf-8"))["session_id"]
        == "sess_repl_001"
    )
    assert captured["session_id"] == "sess_repl_001"
    assert captured["enabled_skills"] == ["tracking", "web_search", "feishu"]
    assert captured["args"].artifacts_root == str(artifacts_root)


def test_main_repl_returns_tui_exit_code(monkeypatch, tmp_path) -> None:
    state_root = tmp_path / "state"
    artifacts_root = tmp_path / "artifacts"
    monkeypatch.setattr("backend.cli._launch_repl_tui", lambda **_kwargs: 17)
    monkeypatch.setattr(
        "sys.argv",
        [
            "robot_agent.py",
            "repl",
            "--session-id",
            "sess_repl_001",
            "--state-root",
            str(state_root),
            "--artifacts-root",
            str(artifacts_root),
        ],
    )

    assert main() == 17


def test_launch_repl_tui_passes_runtime_config(monkeypatch, tmp_path) -> None:
    state_root = tmp_path / "state"
    artifacts_root = tmp_path / "artifacts"
    env_file = tmp_path / ".ENV"
    env_file.write_text("", encoding="utf-8")
    captured = {}

    def fake_run(command, cwd, check):
        captured["command"] = command
        captured["cwd"] = cwd
        captured["check"] = check

        class _Completed:
            returncode = 0

        return _Completed()

    monkeypatch.setattr("backend.cli.subprocess.run", fake_run)
    args = argparse.Namespace(
        device_id="robot_01",
        state_root=str(state_root),
        frame_buffer_size=5,
        env_file=str(env_file),
        artifacts_root=str(artifacts_root),
        pi_binary="pi",
        pi_timeout_seconds=180,
    )

    exit_code = cli_module._launch_repl_tui(
        args=args,
        session_id="sess_repl_001",
        enabled_skills=["tracking", "web_search"],
    )

    assert exit_code == 0
    assert captured["check"] is False
    assert captured["cwd"] == resolve_project_path(".")
    assert captured["command"][0] == "node"
    assert str(resolve_project_path("./terminal/pi_agent_tui.mjs")) in captured["command"]
    assert "--session-id" in captured["command"]
    assert "sess_repl_001" in captured["command"]
    assert "--pi-timeout-seconds" in captured["command"]
    assert "180" in captured["command"]
    assert captured["command"].count("--enabled-skill") == 2
