# Repository Guidelines

## Project Definition
This repository builds a `chat-first`, environment-grounded embodied agent kernel. The current minimal product is not a generic orchestration framework; it is a small runtime where:

- `write environment` keeps world perception alive.
- `e-agent` supervises `pi` on the active session.
- skills provide one-shot task entry or lifecycle control.
- runtime capabilities handle the continuous follow-up path.
- shared session state is the single agent-owned truth.

`tracking` is the primary proof point. `speech` / `tts` and other skills are examples of how new capabilities plug into the same kernel without becoming framework-level special cases.

## Current System Shape
The repository is no longer “moving toward” a minimal kernel; it is already organized around one. Keep these as hard constraints:

- The system is `chat-first`, not perception-first. Turns start from chat, scripts, or interfaces; perception only provides current world grounding.
- `world/perception/` is the only always-on input layer. It may persist same-frame `system1` outputs, but it must not own high-level task orchestration.
- There is one runner path for agent work. Do not add parallel decision paths, detached lifecycle workers, or shadow action authorities.
- Agent-owned persistent state lives in one session-state truth. Avoid duplicate memory mirrors, cache layers, or parallel lifecycle stores.
- `tracking-init`, `tracking-stop`, `tts`, `speech`, and other skills/capabilities should remain ordinary modules with explicit contracts, not plugin-framework magic.
- `interfaces/viewer/` is read-only. It may visualize state, but it must not drive orchestration or become a second runtime.
- Prefer deleting wrappers, compatibility layers, fallback branches, and old stack scripts over rewrapping them.

## Runtime Entry Points
The operator-facing path should stay aligned with `README.md`:

1. `uv run robot-agent-environment-writer --source 0`
2. `uv run e-agent`
3. Optional viewer: `cd interfaces/viewer && npm install && npm run dev`

Current first-class CLI surfaces are:

- `e-agent` -> `agent.e_agent:main`
- `robot-agent` -> `agent.runtime_cli:main`
- `robot-agent-perception` -> `world.perception.cli:main`
- `robot-agent-environment-writer` -> `world.write_environment:main`
- `robot-agent-tracking-benchmark` -> `capabilities.tracking.benchmark:main`

Do not reintroduce deleted wrapper scripts such as tracking stack launchers, frontend shell wrappers, or extra runtime facades unless profiling proves the need.

## Tracking Architecture
`tracking` is intentionally split into two layers:

1. `tracking-init` skill: bind or replace the target from the current visible candidate set, then seed tracking memory.
2. Continuous tracking mini-agent: run follow-up review and rebind on the same session.

Keep the ownership and naming boundaries explicit:

- `skills/tracking/` is the `tracking-init` skill surface. It is only for the one-shot start/replace turn.
- `skills/tracking-stop/` is the `tracking-stop` skill surface. It is only for the one-shot stop/clear turn.
- `capabilities/tracking/` is the continuous tracking runtime surface. It owns the Python `Re -> Act -> Commit` logic, runtime prompts, runtime memory rewrite, and benchmark/runtime helpers.
- Do not mix skill-owned files and runtime-owned files in the same path just because both belong to “tracking”.
- Prompt/template/config ownership must match implementation ownership:
  `tracking-init` prompt assets stay under `skills/tracking/`;
  continuous-tracking and memory-rewrite prompt assets/config stay under `capabilities/tracking/`.
- Naming must make the boundary obvious. Prefer names such as `tracking_init_*`, `tracking_stop_*`, `continuous_tracking_*`, or `tracking_runtime_*` over ambiguous names such as `track_skill_*` when the code is really part of the continuous runtime.

Preserve these design rules from `README.md` and `docs/tracking-runtime-minimal-flow.md`:

- `tracking-init` is one-shot. It selects or replaces the target; it does not own the continuous loop.
- `tracking-stop` is also one-shot. It clears the bound target, pending follow-up, and tracking memory for the active session.
- Continuous tracking lives in `capabilities/tracking/loop.py` and related runtime modules, not in detached stacks or shell wrappers.
- Continuous tracking reads only persisted truth: latest world snapshot, current tracking state, and tracking memory.
- Do not drive continuous tracking from recent dialogue text, ad hoc repo inspection, or raw high-frequency tracker internals.
- Keep the trigger model explicit and small: `chat_init`, `cadence_review`, and `event_rebind`.
- Tracking lifecycle state must have one clear write path. Prefer explicit commits in runner/capability code over generic patch protocols.

Performance guidance from `docs/tracking-single-turn-latency-2026-04-10.md` and `docs/tracking-no-reason-experiment-2026-04-10.md` is also current:

- Keep the live tracking hot path short and failure-visible.
- Do not casually reintroduce verbose `reason`, `candidate_checks`, or similar large structured outputs on the critical path.
- Keep tracking memory rewrite off the hot path unless a measured regression justifies changing that tradeoff.

Benchmark guidance from `docs/tracking-paper-vs-local-results.md` remains in force:

- Benchmark must follow the same snapshot-driven model as runtime.
- Do not let benchmark logic read raw tracker frames as direct tracking-agent input when runtime would read emitted snapshots.
- Treat reported scores as local-system results, not automatic paper reproduction claims.

## Module Boundaries
Keep responsibilities sharp:

- `world/`: always-on environment writing, frame persistence, snapshot truth, same-frame `system1` results.
- `agent/`: active session bootstrap, runner framing, state commit, utility CLI, `e-agent` supervisor.
- `capabilities/`: runtime-owned capability logic such as continuous tracking and benchmark code.
- `skills/`: `pi` skill contracts and skill-local helpers. If a helper exists only for one skill, keep it with that skill.
- `interfaces/`: read-only interfaces such as the local viewer.
- `tests/`: pytest coverage, datasets, and fixtures.

Tracking-specific path rules:

- `skills/tracking/` means `tracking-init`, not the continuous runtime.
- `skills/tracking-stop/` means stop/clear lifecycle control, not target selection and not continuous runtime.
- `capabilities/tracking/` means the continuous tracking runtime and its supporting implementation.
- Do not store continuous runtime prompts/config under `skills/tracking/`.
- Do not store skill contract prompts/helpers under `capabilities/tracking/` unless the file is truly runtime-owned.

If you need a new helper, first check whether it belongs in the owning skill or capability instead of adding another generic layer.

## Coding Rules
Follow current Python conventions:

- 4-space indentation.
- `snake_case` for modules and functions.
- `PascalCase` for dataclasses, stores, and similar types.
- Explicit type hints on public functions.
- Prefer `pathlib.Path` over raw string paths.
- Keep repo-managed JSON stable with `indent=2` and `ensure_ascii=True` when writing files meant to be checked in or compared.

Architecture rules:

- Prefer one obvious code path over abstract routing layers.
- Prefer plain Python modules/functions over registries, plugin systems, or lifecycle frameworks.
- If a helper exists only to bridge an abstraction that should not exist, delete the abstraction.
- New CLI entry points must stay thin adapters over current runner/perception/capability APIs.
- Prefer explicit failure over defensive fallback trees that hide state problems.

Skill/runtime coordination rules:

- Start from the skill contract first when changing a user-facing turn flow.
- If a skill uses runtime env vars such as `ROBOT_AGENT_SESSION_ID` and `ROBOT_AGENT_STATE_ROOT`, prefer them over scanning `.runtime` just to rediscover active state.
- Stop/status turns must not be forced through `tracking-init`.
- Viewer-related data shaping should stay read-only and derived from persisted state.

## Build, Test, and Dev Commands
There is no separate build step. Use Python directly from the repository root.

Core test commands:

```bash
python -m pytest
python -m pytest tests/test_pi_agent_runner.py
python -m pytest tests/test_tracking_agent.py
python -m pytest tests/test_tracking_stop_skill.py
python -m pytest tests/test_cli_surface.py
```

Useful runtime commands:

```bash
uv run robot-agent session-show
uv run robot-agent-perception latest-frame
uv run robot-agent-tracking-benchmark
```

When changing tracking runtime behavior, prefer running the most directly affected test module in addition to the full suite.

## Testing Guidelines
Use `pytest` for all coverage. Name files `test_<module>.py` and functions `test_<behavior>()`.

Add or update tests whenever you change:

- session-state transitions
- tracking triggers or lifecycle behavior
- init / stop skill behavior
- viewer payload shaping
- CLI argument surfaces
- benchmark/runtime coupling

Prefer small fixture-driven tests. Use `tmp_path` or `tmp_path_factory` for runtime directories and generated artifacts.

## Documentation Alignment
Keep repository guidance aligned with current docs:

- `README.md`: operator-facing runtime overview and startup path
- `docs/tracking-runtime-minimal-flow.md`: authoritative tracking split between init and continuous runtime
- `docs/tracking-single-turn-latency-2026-04-10.md`: hot-path latency findings
- `docs/tracking-no-reason-experiment-2026-04-10.md`: no-reason and async rewrite tradeoffs
- `docs/tracking-paper-vs-local-results.md`: benchmark interpretation and local-result framing
- `docs/embodied-agent-architecture-report.html` and `docs/embodied-agent-architecture-presentation.pdf`: architecture narrative and terminology

If you change the runtime shape, operator workflow, or architecture vocabulary, update the relevant docs in the same change instead of letting `AGENTS.md`, `README.md`, and `docs/` drift apart.

## Commit and PR Guidance
Keep commits focused with short imperative subjects, for example `Tighten tracking stop flow`.

PRs should include:

- a short summary
- any `.ENV` or API-setting changes
- the exact test commands run
- sample output or paths only when CLI/operator behavior changed

## Security and Artifacts
Store secrets in `.ENV`; never commit API keys, session outputs, `.runtime` artifacts, sampled video scratch files, or generated caches.

Ignore and avoid committing local artifacts such as:

- `__pycache__/`
- benchmark scratch outputs
- viewer build output unless the task explicitly requires it
- temporary media captures

If you change interfaces used by `skills/tracking/` or `skills/tracking-stop/`, update the corresponding helper scripts and tests in the same change.
