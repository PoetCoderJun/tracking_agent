---
name: feishu
description: Use when the turn should send a Feishu-facing notification or coordination update.
---

# Feishu Skill

## Overview

This skill turns a session outcome or system event into a Feishu notification.

- Use it for notification-style actions, not for tracking or web search.
- Delivery still uses a mock Feishu outbox when real Feishu credentials are absent.

## When to Use

- The user explicitly asks to notify Feishu.
- The latest turn describes a system event that should become a Feishu reminder.
- The turn is about sending a coordination update rather than answering a knowledge question.

Do not use this skill for:

- web lookup turns
- target selection or tracking turns
- generic explanation turns with no notification intent

## Rules

1. Resolve the active session first.
2. In this runtime, prefer `ROBOT_AGENT_SESSION_ID` and `ROBOT_AGENT_STATE_ROOT` from the environment over hardcoded runtime paths.
3. Decide whether this turn should send a Feishu notification.
4. If yes, decide whether to use the PI environment's own integration path or the skill-local helper.
5. Do not route this through backend-owned Feishu skill code.
6. After the send completes, reply naturally to the user with the result.

## Local Helper

If your current PI environment needs a deterministic local helper, use the skill-local script:

- `python -m skills.feishu.scripts.notify_turn --session-id <session-id> --state-root ./.runtime/agent-runtime --artifacts-root ./.runtime/pi-agent --env-file .ENV --title ... --message ...`
- In the normal PI runtime, prefer:
  `python -m skills.feishu.scripts.notify_turn --session-id "$ROBOT_AGENT_SESSION_ID" --state-root "$ROBOT_AGENT_STATE_ROOT" --artifacts-root ./.runtime/pi-agent --env-file .ENV --title "..." --message "..."`

Important:

- The helper writes the side effect and returns machine-readable details for the turn.
- The helper belongs to this skill package; backend does not own Feishu skill logic.
- If `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, and `FEISHU_NOTIFY_RECEIVE_ID` are configured, the helper sends a real Feishu message and still records the mock Feishu outbox entry.
- The helper returns a processed payload; the harness/runner is responsible for the final session-state commit.
- Keep the title short and action-oriented.
- Do not expose helper JSON to the user.

## Output Contract

For handled turns:

1. choose this skill
2. either send through your current environment or call exactly one skill-local helper command
3. answer the user naturally after the send completes
