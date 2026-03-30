# Repository Guidelines

## Project Focus
This repository is for building a generic robot-agent runtime plus pluggable skills, with `skills/tracking/` as the current tracking skill. Keep orchestration, decision-making, and step selection inside the Agent flow; use Python modules and helper scripts only to provide deterministic support such as frame extraction, state persistence, and validation. Apply first-principles thinking to every change: do not add abstraction, branching, or files unless the problem truly requires it, and keep the codebase minimal and orderly.

## Project Structure & Module Organization
Core package code lives in `backend/`. Use `backend/perception/` for environment inputs and frame sampling, `backend/agent/` for agent-owned context, memory, and runtime logic, `backend/persistence/` for save/load adapters, and `backend/actions/` for executable robot interfaces. Tests live in `backend/tests/` and fixtures live in `backend/tests/fixtures/`. The actual Agent workflow prompts, flow definitions, and helper scripts live under `skills/tracking/` and should remain the center of the system design.

## Build, Test, and Development Commands
There is no separate build step; use Python directly from the repository root.

```bash
python -m pytest
python -m pytest backend/tests/test_agent_runner.py
python -m pytest backend/tests/test_tracking_scripts.py
```

The first command runs the full suite. The second and third target a single test module while iterating.

## Coding Style & Naming Conventions
Follow existing Python style: 4-space indentation, `snake_case` for modules/functions, `PascalCase` for dataclasses and store classes, and explicit type hints on public functions. Prefer `pathlib.Path` over raw string paths. New modules should import from `backend.perception`, `backend.agent`, `backend.persistence`, `backend.actions`, or shared root helpers instead of duplicating logic. Keep JSON output stable with `indent=2` and `ensure_ascii=True` when writing repo-managed artifacts. Do not move orchestration logic into helper scripts if it belongs in the Agent skill. Favor the simplest design that satisfies the requirement, and keep modules small, legible, and cleanly separated by responsibility.

## Testing Guidelines
Use `pytest` for all coverage. Name files `test_<module>.py` and functions `test_<behavior>()`. Add or update tests whenever changing frame extraction, runtime state transitions, or skill layout rules. Prefer small fixture-driven tests and use `tmp_path` or `tmp_path_factory` for runtime directories instead of committing generated artifacts.

## Commit & Pull Request Guidelines
Current history uses short imperative commit subjects such as `Initial commit` and `Ignore video artifacts`. Keep commits focused and use the same style, for example `Add runtime state reuse tests`. PRs should include a brief summary, note any `.ENV` or API-setting changes, and list the exact test commands run. Include sample output or paths only when CLI behavior changes.

## Security & Configuration Tips
Store secrets in `.ENV`; never commit API keys, session output, or sampled video assets. Video files are ignored by design. If you change module interfaces used by `skills/tracking/`, update the corresponding flow or helper script in the same change. Any change that affects decision flow should start from the skill contract first, then adjust backend helpers only as needed.
