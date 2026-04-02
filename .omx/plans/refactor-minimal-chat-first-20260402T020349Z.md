## Cleanup Plan

### Objective

Refactor the repository toward a small, chat-first, event-triggered embodied agent kernel:

- `perception` runs continuously and persists world facts
- a single `runner` handles one event at a time
- the agent reads the latest perception context when an event arrives
- `tracking` and `tts` operate as ordinary capability modules

### Target Architecture

1. Keep `perception` as the only always-on subsystem.
2. Collapse runtime orchestration into one runner entrypoint.
3. Replace split runtime state with one session-state source of truth.
4. Treat `tracking` and `tts` as direct capability modules, not framework plugins.
5. Remove or absorb generic patch protocols, detached rewrite workers, and redundant CLI orchestration layers.

### Constraints

- Preserve existing tracking behavior where already protected by tests.
- Keep diffs small and reversible; prefer deletion over addition.
- Do not add dependencies.
- Update repository instructions before broad refactor edits.
- Use OMX team workflow for parallel analysis and verification support.

### Execution Slices

1. Update `AGENTS.md` with the new architectural constraints.
2. Create an OMX context snapshot and launch a 3-worker team for:
   - architecture/file inventory
   - migration slicing
   - verification boundary review
3. Implement the first refactor slice:
   - introduce or define the minimal session-state contract
   - simplify the runner surface
   - narrow tracking/tts integration seams
4. Run focused regression tests around runner, tracking, and persistence.

### Initial Regression Focus

- `backend/tests/test_agent_runner.py`
- `backend/tests/test_tracking_scripts.py`
- `backend/tests/test_backend_store.py`

### Explicit Non-Goals For This Slice

- No new plugin framework
- No new job system
- No new generic event bus
- No frontend/viewer redesign
