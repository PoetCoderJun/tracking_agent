---
name: feishu
description: Use when the turn should send a Feishu-facing notification or coordination update.
---

# Feishu Skill

## Overview

This skill turns a turn outcome or system event into a Feishu notification.

- The runner should still decide whether this skill applies on each turn.
- Use it for notification-style actions, not for tracking or web search.
- In this repository, delivery uses a mock Feishu outbox so the full Pi runner flow can be tested without a real connector.

## When to Use

- The user explicitly asks to notify Feishu.
- The latest turn describes a system event that should be turned into a Feishu reminder.
- The turn is about sending a coordination update rather than answering a knowledge question.

Do not use this skill for:

- web lookup turns
- target selection or tracking turns
- generic explanation turns with no notification intent

## Routing Rules

1. Read `turn_context.json` first.
2. Read `context_paths.route_context_path`.
3. Decide whether this turn should send a Feishu notification.
4. If yes, call the bundled helper, let it send or record the notification, then answer the user naturally.
5. If no, do not force the turn into this skill.

## Helper Script

Use this deterministic helper:

- `python -m skills.feishu.scripts.notify_turn --turn-context-file <turn_context.json> --title ... --message ...`

Important:

- The helper writes the notification side effect and returns machine-readable details for the turn.
- If `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, and `FEISHU_NOTIFY_RECEIVE_ID` are configured, the helper sends a real Feishu bot message first and still records the outbox entry.
- Keep the title short and action-oriented.
- Do not expose the helper JSON to the user.
- After the helper completes, reply naturally to the user with the send result.

## Output Contract

For handled turns:

1. choose this skill
2. call exactly one helper command
3. answer the user naturally after the helper completes

This repository uses mock delivery on purpose so the notification path remains visible and failure-visible during demos.
