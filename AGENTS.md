# Repository Guidelines

## Project Focus
This repository is for building a top-level Tracking Agent skill plus the supporting Python scaffolding it needs. The primary deliverable is the skill behavior in `skills/vision-tracking-skill/` and the runtime helpers around it, not changes to any Agent CLI implementation. Keep orchestration, decision-making, and step selection inside the Agent flow; use Python modules and scaffold scripts only to provide deterministic support such as frame extraction, state persistence, query-plan generation, and validation. Apply first-principles thinking to every change: do not add abstraction, branching, or files unless the problem truly requires it, and keep the codebase minimal and orderly.

## Project Structure & Module Organization
Core package code lives in `tracking_agent/`. Use `tracking_agent/core/` for session and runtime state, `tracking_agent/pipeline/` for frame extraction and query-plan assembly, and root-level modules for shared utilities such as config, memory formatting, image handling, and output validation. Tests live in `tests/` and mirror module names, for example `tests/test_runtime_state.py`. CLI scaffolding lives in `scaffold/cli/`. The actual Agent workflow prompts, flow definitions, and helper scripts live under `skills/vision-tracking-skill/` and should remain the center of the system design.

## Build, Test, and Development Commands
There is no separate build step; use Python directly from the repository root.

```bash
python -m pytest
python -m pytest tests/test_runtime_state.py
python scaffold/cli/build_query_plan.py --video test_data/0045.mp4 --runtime-dir /tmp/tracking-run
```

The first command runs the full suite. The second targets a single test module while iterating. The CLI command samples frames and writes a query plan scaffold for local validation.

## Coding Style & Naming Conventions
Follow existing Python style: 4-space indentation, `snake_case` for modules/functions, `PascalCase` for dataclasses and store classes, and explicit type hints on public functions. Prefer `pathlib.Path` over raw string paths. New modules should import from `tracking_agent.core`, `tracking_agent.pipeline`, or shared root helpers instead of duplicating logic. Keep JSON output stable with `indent=2` and `ensure_ascii=True` when writing repo-managed artifacts. Do not move orchestration logic into scaffold scripts if it belongs in the Agent skill. Favor the simplest design that satisfies the requirement, and keep modules small, legible, and cleanly separated by responsibility.

## Testing Guidelines
Use `pytest` for all coverage. Name files `test_<module>.py` and functions `test_<behavior>()`. Add or update tests whenever changing frame extraction, query-plan generation, runtime state transitions, or skill layout rules. Prefer small fixture-driven tests and use `tmp_path` or `tmp_path_factory` for runtime directories instead of committing generated artifacts.

## Commit & Pull Request Guidelines
Current history uses short imperative commit subjects such as `Initial commit` and `Ignore video artifacts`. Keep commits focused and use the same style, for example `Add runtime state reuse tests`. PRs should include a brief summary, note any `.ENV` or API-setting changes, and list the exact test commands run. Include sample output or paths only when CLI behavior changes.

## Security & Configuration Tips
Store secrets in `.ENV`; never commit API keys, session output, or sampled video assets. Video files are ignored by design. If you change module interfaces used by `skills/vision-tracking-skill/`, update the corresponding flow or helper script in the same change. Any change that affects decision flow should start from the skill contract first, then adjust scaffolding only as needed.
