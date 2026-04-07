from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = ROOT / "agent"
BACKEND_TRACKING_ROOT = ROOT / "backend" / "tracking"
SKILL_ROOT = ROOT / "skills" / "tracking"
WEB_SEARCH_SKILL_ROOT = ROOT / "skills" / "web_search"
FEISHU_SKILL_ROOT = ROOT / "skills" / "feishu"
CLI_PATH = ROOT / "backend" / "cli.py"
TRACKING_SCRIPT_ROOT = SKILL_ROOT / "scripts"
REPO_SCRIPT_ROOT = ROOT / "scripts"
TRACKING_VIEWER_ROOT = ROOT / "viewer"


def test_skill_package_contains_expected_files() -> None:
    expected_paths = [
        SKILL_ROOT / "SKILL.md",
        SKILL_ROOT / "references" / "output-contracts.md",
        SKILL_ROOT / "references" / "interaction-policy.md",
        SKILL_ROOT / "references" / "robot-agent-config.json",
        AGENT_ROOT / "runner.py",
        AGENT_ROOT / "session_store.py",
        BACKEND_TRACKING_ROOT / "cli.py",
        BACKEND_TRACKING_ROOT / "context.py",
        BACKEND_TRACKING_ROOT / "crop.py",
        BACKEND_TRACKING_ROOT / "memory.py",
        BACKEND_TRACKING_ROOT / "payload.py",
        BACKEND_TRACKING_ROOT / "select.py",
        BACKEND_TRACKING_ROOT / "validator.py",
        BACKEND_TRACKING_ROOT / "visualization.py",
        BACKEND_TRACKING_ROOT / "bootstrap.py",
        BACKEND_TRACKING_ROOT / "viewer.py",
        BACKEND_TRACKING_ROOT / "references" / "memory-format.md",
        BACKEND_TRACKING_ROOT / "rewrite_memory.py",
        BACKEND_TRACKING_ROOT / "rewrite_worker.py",
        BACKEND_TRACKING_ROOT / "service.py",
        BACKEND_TRACKING_ROOT / "loop.py",
        REPO_SCRIPT_ROOT / "run_tracking_perception.py",
        REPO_SCRIPT_ROOT / "run_tracking_loop.py",
        REPO_SCRIPT_ROOT / "run_tracking_agent.py",
        REPO_SCRIPT_ROOT / "run_tracking_viewer_stream.py",
        REPO_SCRIPT_ROOT / "run_tracking_viewer_stream.py",
        REPO_SCRIPT_ROOT / "run_tracking_stack.sh",
        REPO_SCRIPT_ROOT / "run_tracking_frontend.sh",
        TRACKING_VIEWER_ROOT / "package.json",
        TRACKING_VIEWER_ROOT / "src" / "App.jsx",
    ]

    for path in expected_paths:
        assert path.exists(), f"Missing expected skill artifact: {path}"


def test_external_skill_wrappers_are_installed() -> None:
    expected_paths = [
        WEB_SEARCH_SKILL_ROOT / "SKILL.md",
        WEB_SEARCH_SKILL_ROOT / "scripts" / "search_turn.py",
        FEISHU_SKILL_ROOT / "SKILL.md",
        FEISHU_SKILL_ROOT / "scripts" / "notify_turn.py",
    ]
    for path in expected_paths:
        assert path.exists(), f"Missing expected external skill artifact: {path}"



def test_backend_contains_single_local_cli_entrypoint() -> None:
    assert CLI_PATH.exists()


def test_tracking_operational_scripts_live_under_repo_scripts() -> None:
    assert (REPO_SCRIPT_ROOT / "run_tracking_perception.py").exists()
    assert (REPO_SCRIPT_ROOT / "run_tracking_loop.py").exists()
    assert (REPO_SCRIPT_ROOT / "run_tracking_agent.py").exists()
    assert (REPO_SCRIPT_ROOT / "run_tracking_viewer_stream.py").exists()
    assert (REPO_SCRIPT_ROOT / "run_tracking_viewer_stream.py").exists()
    assert (REPO_SCRIPT_ROOT / "run_tracking_stack.sh").exists()
    assert (REPO_SCRIPT_ROOT / "run_tracking_frontend.sh").exists()


def test_tracking_canonical_modules_live_under_root_packages() -> None:
    assert (AGENT_ROOT / "runner.py").exists()
    assert (AGENT_ROOT / "session_store.py").exists()
    assert (BACKEND_TRACKING_ROOT / "bootstrap.py").exists()
    assert (BACKEND_TRACKING_ROOT / "cli.py").exists()
    assert (BACKEND_TRACKING_ROOT / "context.py").exists()
    assert (BACKEND_TRACKING_ROOT / "select.py").exists()
    assert (BACKEND_TRACKING_ROOT / "viewer.py").exists()
    assert (BACKEND_TRACKING_ROOT / "service.py").exists()
    assert (BACKEND_TRACKING_ROOT / "loop.py").exists()
    assert (TRACKING_VIEWER_ROOT / "stream.py").exists()


def test_tracking_skill_directory_does_not_host_deterministic_entry_scripts() -> None:
    assert not (TRACKING_SCRIPT_ROOT / "rewrite_memory.py").exists()
    assert not (TRACKING_SCRIPT_ROOT / "run_tracking_init.py").exists()
    assert not (TRACKING_SCRIPT_ROOT / "run_tracking_track.py").exists()
    assert not (TRACKING_SCRIPT_ROOT / "run_tracking_rewrite_worker.py").exists()
    assert not (TRACKING_SCRIPT_ROOT / "select_target.py").exists()
    assert not (TRACKING_SCRIPT_ROOT / "turn_payload.py").exists()
    assert not (TRACKING_SCRIPT_ROOT / "run_tracking_perception.py").exists()
    assert not (TRACKING_SCRIPT_ROOT / "run_tracking_loop.py").exists()


def test_backend_interfaces_directory_is_removed() -> None:
    assert not (ROOT / "backend" / "interfaces").exists()


def test_legacy_turn_runner_artifacts_are_removed() -> None:
    legacy_protocol_name = "cl" "aw_protocol.py"
    legacy_runner_dir = "cl" "aw"

    assert not (ROOT / "agent" / legacy_protocol_name).exists()
    assert not (ROOT / legacy_runner_dir).exists()


def test_repo_uses_single_tracking_skill_location() -> None:
    assert not (SKILL_ROOT / "harness").exists()
    assert not (SKILL_ROOT / "flows").exists()


def test_skill_file_does_not_reference_repo_external_entrypoints() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "backend/interfaces/cli" not in skill


def test_skill_frontmatter_and_sections_follow_skill_style() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert "description: Use when " in skill
    assert "## When to Use" in skill
    assert "## Quick Reference" in skill
    assert "## Tool Rules" in skill
    assert "## Helper Scripts" in skill
    assert "## Output Contract" in skill
    assert "## Canonical References" in skill
    assert "## Common Mistakes" in skill


def test_skill_explicitly_treats_tool_names_as_tools_not_skills() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert "This skill only does one thing: identify which current candidate person the user means." in skill
    assert "If it applies, the skill should help confirm one person." in skill
    assert "This is a one-shot target-selection skill." in skill


def test_pi_specific_configs_are_not_listed_as_canonical_references() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    canonical_start = skill.index("## Canonical References")
    mistakes_start = skill.index("## Common Mistakes")
    canonical_section = skill[canonical_start:mistakes_start]

    assert "agent-config.json" not in canonical_section
    assert "pi-agent-tools.json" not in canonical_section
    assert "robot-agent-config.json" not in canonical_section


def test_tracking_skill_does_not_embed_backend_runtime_contracts() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "backend.tools.tracking" not in skill
    assert "backend/adapters/pi" not in skill
    assert "scripts/runtime.py" not in skill
    assert "python -m backend.tracking.cli init" in skill
    assert "python -m backend.tracking.cli track" not in skill
    assert "skill_state_patch" not in skill
    assert '"status": "idle" | "processed"' not in skill


def test_tracking_skill_uses_generic_turn_context_over_backend_generated_tracking_context() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert "state_paths.session_path" in skill
    assert "--session-file <session.json>" in skill
    assert "context_paths.skill_context_paths" not in skill
    assert "--tracking-context-file <tracking_context.json>" not in skill


def test_tracking_skill_requires_helper_for_explicit_candidate_id_turns() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert "User explicitly says `跟踪 ID 为 N` / `切换到 ID N` | reason in skill, then call backend `init`" in skill
    assert "If yes, call the backend `init` command and return its stdout unchanged." in skill


def test_tracking_skill_excludes_continuation_and_rewrite_language() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert "继续跟踪" not in skill
    assert "continue tracking" not in skill
    assert "grounded tracking Q&A" not in skill
    assert "backend.tracking.select" in skill


def test_memory_reference_clarifies_model_output_vs_stored_json() -> None:
    memory_reference = (BACKEND_TRACKING_ROOT / "references" / "memory-format.md").read_text(
        encoding="utf-8"
    )

    assert "Model output:" in memory_reference
    assert "Stored file:" in memory_reference
    assert "presentation detail" in memory_reference
