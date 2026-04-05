# Repository Guidelines

## Project Focus
This repository is for building a chat-first, event-triggered embodied agent kernel backed by continuous perception, with `tracking` and `tts` as the concrete capability examples. The system should stay small, legible, and hard-edged: one always-on perception layer, one event runner, one session-state source of truth, and capability modules that cooperate through the runner rather than through framework plumbing. Apply first-principles thinking to every change: do not add abstraction, branching, or files unless the problem truly requires it, and keep the codebase minimal and orderly.

## Current Refactor Direction

The repository is actively being reduced from an over-engineered runtime shape toward a minimal kernel. Treat the following as hard constraints for ongoing work:

- The system is `chat-first`, not perception-first. Agent turns are triggered by dialogue, scripts, or interfaces; perception provides current world context when a turn runs.
- `perception` is the only always-on subsystem. It may maintain recent observations and persisted frame data, but it must not own high-level task orchestration.
- There should be a single runner path for handling one event/turn at a time.
- There should be a single persisted session-state truth for agent-owned state. Avoid parallel truth sources and redundant cache layers.
- `tracking` and `tts` should behave like ordinary capability modules, not framework-level plugins.
- Prefer explicit state updates in runner/capability code over generic patch protocols returned by models or helper scripts.
- Avoid or remove detached workers, generic jobs, extra runtime wrappers, and orchestration-heavy CLI layers unless profiling proves they are necessary.
- Prefer deleting and collapsing layers over renaming or rewrapping them.
- At any time, prefer deleting compatibility surfaces, fallback paths, and defensive over-handling so the system stays on one clear, strict, failure-visible MVP path.

## Project Structure & Module Organization
Core package code lives in `backend/`. Keep long-running world observation in `backend/perception/`. Keep event handling, state reduction, and capability invocation in the runner/agent path. Keep executable robot interfaces in `backend/actions/`. Tests live in `backend/tests/` and fixtures live in `backend/tests/fixtures/`. Capability-specific helper logic should stay close to the capability that owns it; avoid rebuilding a generic runtime framework around those helpers.

## Build, Test, and Development Commands
There is no separate build step; use Python directly from the repository root.

```bash
python -m pytest
python -m pytest backend/tests/test_agent_runner.py
python -m pytest backend/tests/test_tracking_scripts.py
```

The first command runs the full suite. The second and third target a single test module while iterating.

## Coding Style & Naming Conventions
Follow existing Python style: 4-space indentation, `snake_case` for modules/functions, `PascalCase` for dataclasses and store classes, and explicit type hints on public functions. Prefer `pathlib.Path` over raw string paths. Keep JSON output stable with `indent=2` and `ensure_ascii=True` when writing repo-managed artifacts. Favor the simplest design that satisfies the requirement, and keep modules small, legible, and cleanly separated by responsibility.

Architecture guardrails:

- Prefer one obvious code path over “generic” routing layers.
- Prefer one state model over multiple cache or memory mirrors.
- Prefer plain Python modules and functions over registries, plugin systems, or lifecycle frameworks.
- If a helper exists only to bridge abstractions that should not exist, delete the abstraction rather than adding another helper.
- New CLI or script entrypoints must stay thin adapters over the core runner/perception APIs.

## Testing Guidelines
Use `pytest` for all coverage. Name files `test_<module>.py` and functions `test_<behavior>()`. Add or update tests whenever changing frame extraction, runtime state transitions, or skill layout rules. Prefer small fixture-driven tests and use `tmp_path` or `tmp_path_factory` for runtime directories instead of committing generated artifacts.

## Commit & Pull Request Guidelines
Current history uses short imperative commit subjects such as `Initial commit` and `Ignore video artifacts`. Keep commits focused and use the same style, for example `Add runtime state reuse tests`. PRs should include a brief summary, note any `.ENV` or API-setting changes, and list the exact test commands run. Include sample output or paths only when CLI behavior changes.

## Security & Configuration Tips
Store secrets in `.ENV`; never commit API keys, session output, or sampled video assets. Video files are ignored by design. If you change module interfaces used by `skills/tracking/`, update the corresponding flow or helper script in the same change. Any change that affects decision flow should start from the skill contract first, then adjust backend helpers only as needed.
