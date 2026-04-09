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
4. If yes, call the bundled helper once.
5. After the helper completes, reply naturally to the user with the send result.

## Helper Script

Use this deterministic helper:

- `python -m skills.feishu.scripts.notify_turn --session-id <session-id> --state-root ./.runtime/agent-runtime --artifacts-root ./.runtime/pi-agent --env-file .ENV --title ... --message ...`
- In the normal PI runtime, prefer:
  `python -m skills.feishu.scripts.notify_turn --session-id "$ROBOT_AGENT_SESSION_ID" --state-root "$ROBOT_AGENT_STATE_ROOT" --artifacts-root ./.runtime/pi-agent --env-file .ENV --title "..." --message "..."`

Important:

- The helper writes the side effect and returns machine-readable details for the turn.
- The helper is only a thin entrypoint; backend turn logic assembles and applies the processed payload.
- If `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, and `FEISHU_NOTIFY_RECEIVE_ID` are configured, the helper sends a real Feishu message and still records the mock Feishu outbox entry.
- Keep the title short and action-oriented.
- Do not expose helper JSON to the user.

## Output Contract

For handled turns:

1. choose this skill
2. call exactly one helper command
3. answer the user naturally after the helper completes
