from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = ROOT / "skills" / "tracking"
TRACKING_CORE_ROOT = SKILL_ROOT / "core"
SPEECH_SKILL_ROOT = ROOT / "skills" / "speech"
CLI_PATH = ROOT / "backend" / "cli.py"
TRACKING_SCRIPT_ROOT = SKILL_ROOT / "scripts"
REPO_SCRIPT_ROOT = ROOT / "scripts"
TRACKING_VIEWER_ROOT = ROOT / "apps" / "tracking-viewer"
PI_SETTINGS_PATH = ROOT / ".pi" / "settings.json"


def test_skill_package_contains_expected_files() -> None:
    expected_paths = [
        SKILL_ROOT / "SKILL.md",
        SKILL_ROOT / "references" / "memory-format.md",
        SKILL_ROOT / "references" / "output-contracts.md",
        SKILL_ROOT / "references" / "interaction-policy.md",
        SKILL_ROOT / "references" / "robot-agent-config.json",
        TRACKING_CORE_ROOT / "select.py",
        TRACKING_CORE_ROOT / "payload.py",
        TRACKING_CORE_ROOT / "context.py",
        TRACKING_CORE_ROOT / "memory.py",
        TRACKING_CORE_ROOT / "crop.py",
        TRACKING_CORE_ROOT / "validator.py",
        TRACKING_CORE_ROOT / "visualization.py",
        TRACKING_SCRIPT_ROOT / "rewrite_memory.py",
        TRACKING_SCRIPT_ROOT / "run_tracking_init.py",
        TRACKING_SCRIPT_ROOT / "run_tracking_track.py",
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


def test_speech_skill_is_installed_from_hub() -> None:
    expected_paths = [
        SPEECH_SKILL_ROOT / "SKILL.md",
        SPEECH_SKILL_ROOT / "scripts" / "text_to_speech.py",
        SPEECH_SKILL_ROOT / "references" / "cli.md",
    ]
    for path in expected_paths:
        assert path.exists(), f"Missing expected speech artifact: {path}"


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


def test_tracking_skill_scripts_only_keep_single_turn_helpers() -> None:
    assert (TRACKING_SCRIPT_ROOT / "rewrite_memory.py").exists()
    assert (TRACKING_SCRIPT_ROOT / "run_tracking_init.py").exists()
    assert (TRACKING_SCRIPT_ROOT / "run_tracking_track.py").exists()
    assert not (TRACKING_SCRIPT_ROOT / "run_tracking_rewrite_worker.py").exists()
    assert not (TRACKING_SCRIPT_ROOT / "select_target.py").exists()
    assert not (TRACKING_SCRIPT_ROOT / "turn_payload.py").exists()
    assert not (TRACKING_SCRIPT_ROOT / "run_tracking_perception.py").exists()
    assert not (TRACKING_SCRIPT_ROOT / "run_tracking_loop.py").exists()


def test_backend_interfaces_directory_is_removed() -> None:
    assert not (ROOT / "backend" / "interfaces").exists()


def test_repo_uses_single_tracking_skill_location() -> None:
    assert PI_SETTINGS_PATH.exists()
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

    assert "`reply`, `init`, and `track` are turn types" in skill
    assert "deterministic scripts" in skill


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
    assert "python skills/tracking/scripts/run_tracking_init.py" in skill
    assert "python skills/tracking/scripts/run_tracking_track.py" in skill
    assert "skill_state_patch" not in skill
    assert '"status": "idle" | "processed"' not in skill


def test_tracking_skill_requires_helper_for_explicit_candidate_id_turns() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert "User explicitly says `跟踪 ID 为 N` / `切换到 ID N` | `init`" in skill
    assert "Always call the deterministic init script." in skill


def test_tracking_skill_requires_memory_rewrite_after_successful_init_or_track() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert "For `init`, memory rewrite is off the critical path." in skill
    assert "For `track`, memory rewrite is off the critical path." in skill
    assert "Do not call `skills/tracking/core/select.py` or `skills/tracking/scripts/rewrite_memory.py` directly from Pi" in skill


def test_memory_reference_clarifies_model_output_vs_stored_json() -> None:
    memory_reference = (SKILL_ROOT / "references" / "memory-format.md").read_text(
        encoding="utf-8"
    )

    assert "Model output:" in memory_reference
    assert "Stored file:" in memory_reference
    assert "presentation detail" in memory_reference
