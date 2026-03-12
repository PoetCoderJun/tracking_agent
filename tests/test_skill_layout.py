from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "vision-tracking-skill"
SCAFFOLD_ROOT = ROOT / "scaffold" / "cli"


def test_skill_package_contains_expected_files() -> None:
    expected_paths = [
        SKILL_ROOT / "SKILL.md",
        SKILL_ROOT / "agents" / "openai.yaml",
        SKILL_ROOT / "flows" / "init.md",
        SKILL_ROOT / "flows" / "localize.md",
        SKILL_ROOT / "flows" / "update-memory.md",
        SKILL_ROOT / "flows" / "clarify.md",
        SKILL_ROOT / "flows" / "answer-chat.md",
        SKILL_ROOT / "references" / "memory-format.md",
        SKILL_ROOT / "references" / "output-contracts.md",
        SKILL_ROOT / "references" / "prompting-guidelines.md",
        SKILL_ROOT / "references" / "interaction-policy.md",
        SKILL_ROOT / "references" / "agent-config.json",
        SKILL_ROOT / "references" / "pi-agent-tools.json",
        SKILL_ROOT / "references" / "pi-host-agent-config.json",
        SKILL_ROOT / "scripts" / "build_query_plan.py",
        SKILL_ROOT / "scripts" / "track_from_description.py",
        SKILL_ROOT / "scripts" / "frame_manifest_reader.py",
        SKILL_ROOT / "scripts" / "session_store.py",
        SKILL_ROOT / "scripts" / "history_queue.py",
        SKILL_ROOT / "scripts" / "runtime_state.py",
        SKILL_ROOT / "scripts" / "main_agent_locate.py",
        SKILL_ROOT / "scripts" / "sub_agent_memory.py",
        SKILL_ROOT / "scripts" / "answer_tracking_chat.py",
        SKILL_ROOT / "scripts" / "target_crop.py",
        SKILL_ROOT / "scripts" / "bbox_visualization.py",
        SKILL_ROOT / "scripts" / "memory_rewriter.py",
        SKILL_ROOT / "scripts" / "output_validator.py",
        SKILL_ROOT / "scripts" / "agent_common.py",
        SKILL_ROOT / "scripts" / "pi_agent_adapter.py",
        SKILL_ROOT / "scripts" / "pi_backend_bridge.py",
        SKILL_ROOT / "scripts" / "pi_host_turn.py",
    ]

    for path in expected_paths:
        assert path.exists(), f"Missing expected skill artifact: {path}"


def test_scaffold_contains_expected_cli_entrypoints() -> None:
    expected_paths = [
        SCAFFOLD_ROOT / "build_query_plan.py",
    ]

    for path in expected_paths:
        assert path.exists(), f"Missing expected scaffold CLI: {path}"


def test_integration_harness_exists_outside_scaffold() -> None:
    assert (ROOT / "tests" / "integration" / "run_live_session_harness.py").exists()


def test_scaffold_does_not_contain_live_session_runner() -> None:
    assert not (SCAFFOLD_ROOT / "run_live_session.py").exists()


def test_skill_file_does_not_reference_repo_external_entrypoints() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "scaffold/cli" not in skill
