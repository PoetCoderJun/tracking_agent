Task statement

Execute blueprint phases 1, 2, 3, 4, and 6 for the tracking runtime:
- phase 1: shrink and clarify state model
- phase 2: reduce CLI entrypoint surface
- phase 3: move tracking-specific view/context logic out of generic backend layers
- phase 4: simplify tracking loop responsibilities
- phase 6: clean tests so they protect behavior rather than wrapper structure

Desired outcome

- Fewer user-facing and internal CLI entrypoints
- Fewer overlapping state sources and duplicated state semantics
- Cleaner tracking/backend boundaries
- A thinner tracking loop
- Green regression tests after changes

Known facts and evidence

- `scripts/run_tracking_stack.py` exposes 36 CLI arguments and reconstructs commands for perception, loop, viewer, and chat bootstrap.
- `scripts/run_tracking_loop.py` currently mixes scheduling, tracking-policy branching, viewer startup, crop persistence, and rewrite scheduling.
- `scripts/run_tracking_agent.py` overlaps heavily with `run_tracking_loop.py` as another orchestration wrapper.
- `backend/persistence/live_session_store.py` contains tracking-specific frame cleanup behavior by reading `agent_memory.json`.
- `backend/agent/context_views.py` imports tracking memory formatting from `skills.tracking`.
- `backend/perception/bundle.py` includes `tracking_summary`, showing backend-to-skill coupling.
- Current worktree is already dirty and includes in-progress tracking refactor files; avoid reverting unrelated edits.

Constraints

- No new dependencies.
- Keep diffs reviewable and behavior-preserving.
- Respect current dirty worktree and avoid clobbering user changes.
- Follow regression-tests-first cleanup workflow.
- Prefer deletion and consolidation over new abstraction.

Unknowns and open questions

- Whether `scripts/run_tracking_agent.py` should be fully deleted now or reduced to a compatibility shim.
- How far session vs agent-memory consolidation can go without touching external expectations.
- Whether any external user flow depends on current stack/loop argument parity.

Likely touchpoints

- `backend/agent/runtime.py`
- `backend/persistence/live_session_store.py`
- `backend/agent/context_views.py`
- `backend/perception/bundle.py`
- `backend/agent/runner.py`
- `backend/agent/tracking_orchestration.py`
- `scripts/run_tracking_stack.py`
- `scripts/run_tracking_loop.py`
- `scripts/run_tracking_agent.py`
- `skills/tracking/viewer_stream.py`
- relevant tests under `backend/tests/`
