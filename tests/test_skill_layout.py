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
        SKILL_ROOT / "scripts" / "frame_manifest_reader.py",
        SKILL_ROOT / "scripts" / "session_store.py",
        SKILL_ROOT / "scripts" / "history_queue.py",
        SKILL_ROOT / "scripts" / "memory_rewriter.py",
        SKILL_ROOT / "scripts" / "output_validator.py",
    ]

    for path in expected_paths:
        assert path.exists(), f"Missing expected skill artifact: {path}"


def test_scaffold_contains_expected_cli_entrypoints() -> None:
    expected_paths = [
        SCAFFOLD_ROOT / "build_query_plan.py",
        SCAFFOLD_ROOT / "run_session.py",
        SCAFFOLD_ROOT / "run_bbox_inference.py",
        SCAFFOLD_ROOT / "benchmark_tracking.py",
    ]

    for path in expected_paths:
        assert path.exists(), f"Missing expected scaffold CLI: {path}"
