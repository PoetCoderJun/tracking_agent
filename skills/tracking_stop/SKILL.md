---
name: tracking_stop
description: Use when the user asks to stop, cancel, clear, or end the current tracking target or continuous tracking loop.
---

# Tracking Stop Skill

## Overview

This skill stops the current tracking target and clears the continuous tracking state for the active session.

- Use it for explicit stop requests such as `停止跟踪` / `别跟了` / `取消当前跟踪`.
- This is a single-call lifecycle control skill.
- In the normal PI runtime, the helper should be the first tool action.

## When to Use

- The user explicitly asks to stop the current tracking task.
- The user asks to cancel, clear, or end the current tracked target.
- The turn should release the bound target instead of selecting a new one.

Do not use this skill for:

- selecting or replacing a target person
- asking what is currently visible in the frame
- continuing or reviewing an already-running tracking task

## Rules

1. Decide only whether the turn is asking to stop the current tracking task.
2. For a clear stop request, call the skill-local helper exactly once as your first tool action.
3. In this runtime, prefer `ROBOT_AGENT_SESSION_ID` and `ROBOT_AGENT_STATE_ROOT` from the environment over manual runtime inspection.
4. Do not read `.runtime`, inspect repository files, or echo env vars before the helper when the runtime env vars are already expected.
5. Do not route stop requests through the tracking init helper.
6. After the helper completes, answer the user naturally with the stop result.

## Local Helper

If your current PI environment needs a deterministic local helper, use the skill-local script:

- In the normal PI runtime, prefer:
  `python -m skills.tracking_stop.scripts.stop_turn`
- If the runtime env vars are not present, pass the explicit session/state arguments:
  `python -m skills.tracking_stop.scripts.stop_turn --session-id <session-id> --state-root ./.runtime/agent-runtime`

Important:

- The helper clears the active tracking target, cancels pending tracking follow-up, and resets the tracking memory snapshot for the session.
- If there is no active tracking target, the helper returns a natural no-op response.
- The helper belongs to this skill package; backend does not own stop-skill lifecycle logic.
- Do not expose helper JSON to the user.

## Output Contract

For handled turns:

1. choose this skill
2. call exactly one skill-local stop helper command
3. answer the user naturally from the helper result
