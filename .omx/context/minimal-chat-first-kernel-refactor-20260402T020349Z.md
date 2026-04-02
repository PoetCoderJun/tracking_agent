## Task Statement

Refactor the repository toward a minimal chat-first, event-triggered embodied agent kernel with continuous perception and capability modules for tracking and tts.

## Desired Outcome

- Repository instructions explicitly enforce the new direction.
- Current codebase is mapped to a smaller target architecture.
- First refactor slice is clear, bounded, and safe to implement.
- Verification boundaries are identified before broad structural edits.

## Known Facts / Evidence

- The current repository already contains useful perception and tracking domain logic.
- The current runtime is fragmented across runner/runtime/orchestration/state/cache layers.
- The worktree is already dirty; the team should avoid broad overlapping edits without coordination.
- `AGENTS.md` has been updated to enforce:
  - chat-first trigger model
  - continuous perception as the only always-on subsystem
  - single runner path
  - single session-state truth
  - tracking and tts as ordinary capabilities
  - no generic patch protocol / jobs creep

## Constraints

- No new dependencies.
- Prefer deletion over addition.
- Preserve behavior protected by focused runner/tracking/persistence tests.
- Keep diffs small and reversible.
- Do not re-expand the architecture with registries, plugin frameworks, jobs, or detached orchestration layers.

## Unknowns / Open Questions

- Which current files can be preserved with light adaptation versus rewritten or deleted.
- How much of current persistence can be collapsed without breaking tests.
- Which current tracking integration seams are already stable enough to reuse directly.

## Likely Codebase Touchpoints

- `AGENTS.md`
- `backend/agent/runner.py`
- `backend/agent/runtime.py`
- `backend/agent/tracking_orchestration.py`
- `backend/agent/memory.py`
- `backend/persistence/live_session_store.py`
- `backend/perception/service.py`
- `skills/tracking/core/select.py`
- `skills/tracking/core/memory.py`
- `skills/speech/scripts/text_to_speech.py`
- `backend/tests/test_agent_runner.py`
- `backend/tests/test_backend_store.py`
- `backend/tests/test_tracking_scripts.py`
