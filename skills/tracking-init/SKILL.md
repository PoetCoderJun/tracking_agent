---
name: tracking-init
description: Use when one turn asks the robot to start tracking or replace the tracked person with one visible person, whether by natural-language appearance description or explicit candidate ID.
---

# Tracking-Init Skill

## Overview

This skill only does one thing: bind or replace the tracked person from the current visible candidate set.

- Use it when the user is defining or replacing the tracked person.
- This is a one-shot target-selection skill.
- Continuous tracking is a separate Python runtime path under `capabilities/tracking/`; it is not owned by this skill.
- It is not for long-running continuation or polling; those stay in the runtime loop.
- Natural-language requests such as `请跟踪穿黑衣服的人` and `跟踪前面那个黑衣服的人` belong here.
- For a clear bind/init request, the first tool action is the tracking helper.
- In this runtime, `ROBOT_AGENT_SESSION_ID` and `ROBOT_AGENT_STATE_ROOT` are already available. Do not browse `.runtime` or echo env vars before calling the helper.
- If you need current visual grounding, read `$ROBOT_AGENT_STATE_ROOT/perception/latest_frame.jpg` directly; do not read `snapshot.json` first just to discover the image path.
- `snapshot.json` and historical frames still matter as structured/history truth, but the current visual fast path is the stable image file above.
- Do not inspect repository files, runtime directories, or explain the codebase before deciding whether this skill applies.

## When to Use

- The user is defining the target person.
- The user is replacing the current target with another person.
- The user explicitly names a candidate ID such as `跟踪 ID 为 N` or `切换到 ID N`.
- The user points out one visible person by appearance, position, or distinguishing description such as `请跟踪穿黑衣服的人`.
- The turn depends on the current candidate boxes in the latest frame.

Do not use this skill for:

- lifecycle control turns
- status / explanation turns
- continuation turns where the target is already bound and the user is not selecting a new person
- stop requests such as `停止跟踪` or `取消跟踪`; use the tracking-stop skill instead
- long-running daemon or polling work

## Quick Reference

| Situation | Preferred move |
| --- | --- |
| User defines or replaces a visible target | call the tracking helper immediately |
| User explicitly says `跟踪 ID 为 N` / `切换到 ID N` | call the tracking helper immediately |
| User says `请跟踪穿黑衣服的人` / `跟踪前面那个黑衣服的人` | call the tracking helper immediately |
| User says `请持续跟踪` and no target is currently bound | call the tracking helper immediately |
| User asks `当前跟踪状态呢` / `还在跟吗` | do not use init |
| User asks `停止跟踪` / `取消跟踪` | use the tracking-stop skill |
| Explicit candidate ID is invalid | processed clarification |
| Candidate identity is ambiguous | ask one focused clarification question |

## Rules

1. Decide only whether the current turn is binding or replacing one visible person from the current candidate set.
2. If the request is a clear bind/init request, call the tracking skill's own helper exactly once as your first tool action.
3. In this repo, prefer the already-exported env vars `ROBOT_AGENT_SESSION_ID` and `ROBOT_AGENT_STATE_ROOT` over manual runtime inspection.
4. Do not preflight by reading `.runtime`, echoing env vars, re-reading `snapshot.json` just to find the current image path, or re-checking session/state when the normal runtime env vars are already expected.
5. Do not turn lifecycle, status, explanation, or already-bound continuation turns into init.
6. If the user has not given enough stable appearance evidence, ask one focused clarification question.
7. Do not route this through `backend.cli` just because the tracking skill is active.
8. Return the helper output unchanged.

## Local Helper

If your current PI environment needs a deterministic local helper, use the tracking skill's own script:

- In the normal PI runtime, prefer:
  `python ./skills/tracking-init/scripts/init_turn.py --text "..."`
- If the runtime env vars are not present, pass the explicit session/state arguments:
  `python ./skills/tracking-init/scripts/init_turn.py --session-id <session-id> --state-root ./.runtime/agent-runtime --artifacts-root ./.runtime/pi-agent --text "..."`

Important:

- This helper already performs deterministic person selection and assembles the final JSON payload expected by the runtime.
- In the normal PI runtime, `ROBOT_AGENT_SESSION_ID` and `ROBOT_AGENT_STATE_ROOT` are already exported, so the short command is the happy path.
- Do not call backend helper modules such as `capabilities.tracking.select` directly.
- Do not rewrite the final JSON by hand after the helper returns it.

## Output Contract

For target-selection turns:

1. decide that the user is selecting one person
2. call exactly one skill-local deterministic helper when needed
3. return its JSON unchanged

For ambiguity:

1. keep the turn processed
2. ask one focused clarification question about stable appearance differences

## Canonical References

- [output-contracts.md](./references/output-contracts.md)

## Common Mistakes

- Mixing target selection with unrelated turn types.
- Treating a natural-language tracking request as a code-analysis task.
- Reading `.runtime` or repository files before making the first routing decision for a natural-language tracking request.
- Calling backend helper modules manually when the backend command already performs deterministic selection.
- Rewriting the final JSON by hand after the backend command has already returned it.
