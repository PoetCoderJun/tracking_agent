import json

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


def test_parse_args_start_accepts_skill_selection(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "robot_agent.py",
            "start",
            "--session-id",
            "sess_001",
            "--skill",
            "tracking",
            "--skill",
            "speech",
        ],
    )

    args = parse_args()

    assert args.command == "start"
    assert args.session_id == "sess_001"
    assert args.skills == ["tracking", "speech"]


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
    monkeypatch.setattr(
        "sys.argv",
        [
            "robot_agent.py",
            "start",
            "--state-root",
            str(state_root),
            "--skill",
            "tracking",
            "--skill",
            "speech",
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

    assert payload["enabled_skills"] == ["tracking", "speech"]
    assert session_payload["environment_map"]["agent_runtime"]["enabled_skills"] == ["tracking", "speech"]
    assert active_session["session_id"] == session_id
