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
    agent_memory = json.loads(
        (
            resolve_project_path(str(state_root))
            / "sessions"
            / session_id
            / "agent_memory.json"
        ).read_text(encoding="utf-8")
    )
    active_session = json.loads(
        (resolve_project_path(str(state_root)) / "active_session.json").read_text(encoding="utf-8")
    )

    assert payload["enabled_skills"] == ["tracking", "speech"]
    assert agent_memory["environment_map"]["agent_runtime"]["enabled_skills"] == ["tracking", "speech"]
    assert active_session["session_id"] == session_id
