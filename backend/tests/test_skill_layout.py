from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND_TRACKING_ROOT = ROOT / "backend" / "tracking"
BACKEND_WEB_SEARCH_PATH = ROOT / "backend" / "web_search.py"
BACKEND_FEISHU_PATH = ROOT / "backend" / "feishu.py"
BACKEND_DESCRIBE_IMAGE_PATH = ROOT / "backend" / "describe_image.py"
RUNTIME_SESSION_PATH = ROOT / "backend" / "runtime_session.py"
SKILL_ROOT = ROOT / "skills" / "tracking"
WEB_SEARCH_SKILL_ROOT = ROOT / "skills" / "web-search"
FEISHU_SKILL_ROOT = ROOT / "skills" / "feishu"
DESCRIBE_IMAGE_SKILL_ROOT = ROOT / "skills" / "describe-image"
CLI_PATH = ROOT / "backend" / "cli.py"
TRACKING_VIEWER_ROOT = ROOT / "viewer"


def test_skill_package_contains_expected_files() -> None:
    expected_paths = [
        SKILL_ROOT / "SKILL.md",
        SKILL_ROOT / "references" / "output-contracts.md",
        SKILL_ROOT / "references" / "interaction-policy.md",
        RUNTIME_SESSION_PATH,
        BACKEND_TRACKING_ROOT / "cli.py",
        BACKEND_TRACKING_ROOT / "context.py",
        BACKEND_TRACKING_ROOT / "crop.py",
        BACKEND_TRACKING_ROOT / "memory.py",
        BACKEND_TRACKING_ROOT / "payload.py",
        BACKEND_TRACKING_ROOT / "select.py",
        BACKEND_TRACKING_ROOT / "validator.py",
        BACKEND_TRACKING_ROOT / "visualization.py",
        BACKEND_TRACKING_ROOT / "viewer.py",
        BACKEND_TRACKING_ROOT / "rewrite_memory.py",
        BACKEND_TRACKING_ROOT / "loop.py",
        BACKEND_WEB_SEARCH_PATH,
        BACKEND_FEISHU_PATH,
        BACKEND_DESCRIBE_IMAGE_PATH,
        ROOT / "scripts" / "run_perception.py",
        ROOT / "scripts" / "run_tracking_perception.py",
        ROOT / "scripts" / "run_tracking_loop.py",
        ROOT / "scripts" / "run_tracking_viewer_stream.py",
        ROOT / "scripts" / "run_tracking_stack.sh",
        ROOT / "scripts" / "run_tracking_frontend.sh",
        TRACKING_VIEWER_ROOT / "package.json",
        TRACKING_VIEWER_ROOT / "src" / "App.jsx",
    ]
    for path in expected_paths:
        assert path.exists(), f"Missing expected artifact: {path}"


def test_external_skill_wrappers_are_installed() -> None:
    expected_paths = [
        WEB_SEARCH_SKILL_ROOT / "SKILL.md",
        WEB_SEARCH_SKILL_ROOT / "scripts" / "search_turn.py",
        FEISHU_SKILL_ROOT / "SKILL.md",
        FEISHU_SKILL_ROOT / "scripts" / "notify_turn.py",
        DESCRIBE_IMAGE_SKILL_ROOT / "SKILL.md",
        DESCRIBE_IMAGE_SKILL_ROOT / "scripts" / "describe_turn.py",
    ]
    for path in expected_paths:
        assert path.exists(), f"Missing expected external skill artifact: {path}"


def test_backend_contains_single_local_cli_entrypoint() -> None:
    assert CLI_PATH.exists()


def test_legacy_turn_runner_artifacts_are_removed() -> None:
    assert not (ROOT / "agent").exists()
    assert not (ROOT / "terminal" / "pi_agent_tui.mjs").exists()
    assert not (ROOT / "terminal" / "package.json").exists()
    assert not (ROOT / "scripts" / "run_tracking_agent.py").exists()
    assert not (BACKEND_TRACKING_ROOT / "service.py").exists()
    assert not (BACKEND_TRACKING_ROOT / "rewrite_worker.py").exists()


def test_tracking_skill_contract_is_pi_native() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "turn_context.json" not in skill
    assert "route_context" not in skill
    assert "python -m backend.cli tracking-init" in skill
    assert "--session-id <session-id>" in skill


def test_web_search_skill_contract_is_pi_native() -> None:
    skill = (WEB_SEARCH_SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "turn_context.json" not in skill
    assert "route_context" not in skill
    assert "--session-id <session-id>" in skill
    assert "python ./skills/web-search/scripts/search_turn.py" in skill
    assert "backend" in skill


def test_feishu_skill_contract_is_pi_native() -> None:
    skill = (FEISHU_SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "turn_context.json" not in skill
    assert "route_context" not in skill
    assert "--session-id <session-id>" in skill
    assert "python -m skills.feishu.scripts.notify_turn" in skill
    assert "backend" in skill


def test_describe_image_skill_contract_is_pi_native() -> None:
    skill = (DESCRIBE_IMAGE_SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "turn_context.json" not in skill
    assert "route_context" not in skill
    assert "./.runtime/agent-runtime/perception/snapshot.json" in skill
    assert "latest_frame.image_path" in skill
    assert "answer the user naturally" in skill
    assert "Do not call `describe_turn.py`" in skill


def test_external_skill_scripts_are_thin_backend_adapters() -> None:
    web_search = (WEB_SEARCH_SKILL_ROOT / "scripts" / "search_turn.py").read_text(encoding="utf-8")
    feishu = (FEISHU_SKILL_ROOT / "scripts" / "notify_turn.py").read_text(encoding="utf-8")
    describe_image = (DESCRIBE_IMAGE_SKILL_ROOT / "scripts" / "describe_turn.py").read_text(encoding="utf-8")

    assert "run_web_search_turn" in web_search
    assert "run_notify_turn" in feishu
    assert "run_describe_turn" in describe_image

    assert "processed_skill_payload" not in web_search
    assert "apply_processed_payload" not in web_search
    assert "processed_skill_payload" not in feishu
    assert "apply_processed_payload" not in feishu
    assert "processed_skill_payload" not in describe_image
    assert "apply_processed_payload" not in describe_image
