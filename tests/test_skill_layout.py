from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "vision-tracking-skill"
SCAFFOLD_ROOT = ROOT / "scaffold" / "cli"


def test_skill_package_contains_expected_files() -> None:
    expected_paths = [
        SKILL_ROOT / "SKILL.md",
        SKILL_ROOT / "agents" / "openai.yaml",
        SKILL_ROOT / "flows" / "init-tool.md",
        SKILL_ROOT / "flows" / "track-tool.md",
        SKILL_ROOT / "flows" / "rewrite-memory-tool.md",
        SKILL_ROOT / "flows" / "clarify-flow.md",
        SKILL_ROOT / "flows" / "reply-tool.md",
        SKILL_ROOT / "references" / "memory-format.md",
        SKILL_ROOT / "references" / "output-contracts.md",
        SKILL_ROOT / "references" / "prompting-guidelines.md",
        SKILL_ROOT / "references" / "interaction-policy.md",
        SKILL_ROOT / "references" / "agent-config.json",
        SKILL_ROOT / "references" / "pi-agent-tools.json",
        SKILL_ROOT / "scripts" / "build_query_plan.py",
        SKILL_ROOT / "scripts" / "track_from_description.py",
        SKILL_ROOT / "scripts" / "main_agent_locate.py",
        SKILL_ROOT / "scripts" / "sub_agent_memory.py",
        SKILL_ROOT / "scripts" / "agent_common.py",
        SKILL_ROOT / "scripts" / "pi_agent_adapter.py",
        SKILL_ROOT / "scripts" / "pi_backend_bridge.py",
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


def test_skill_frontmatter_and_sections_follow_skill_style() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert "description: Use when " in skill
    assert "## When to Use" in skill
    assert "## Quick Reference" in skill
    assert "## Canonical References" in skill
    assert "## Integration Artifacts" in skill
    assert "## Common Mistakes" in skill


def test_skill_explicitly_treats_tool_names_as_tools_not_skills() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert "`reply`, `init`, `track`, and `rewrite_memory` are tools" in skill
    assert "not standalone skills" in skill


def test_pi_specific_configs_are_not_listed_as_canonical_references() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    canonical_start = skill.index("## Canonical References")
    integration_start = skill.index("## Integration Artifacts")
    canonical_section = skill[canonical_start:integration_start]

    assert "agent-config.json" not in canonical_section
    assert "pi-agent-tools.json" not in canonical_section
    assert "robot-agent-config.json" not in canonical_section


def test_memory_reference_clarifies_model_output_vs_stored_markdown() -> None:
    memory_reference = (SKILL_ROOT / "references" / "memory-format.md").read_text(
        encoding="utf-8"
    )

    assert "Model output:" in memory_reference
    assert "Stored file:" in memory_reference
    assert "storage detail" in memory_reference
