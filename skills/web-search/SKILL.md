---
name: web-search
description: Use when the user needs current web information, links, or source-backed lookup results.
---

# Web Search Skill

## Overview

This skill handles current-information questions that require searching the web.

- Use it for online lookup, not for local docs or robot perception.
- The latest user message in the active session is the default query if you do not pass one explicitly.

## When to Use

- The user asks to search the web.
- The user asks for up-to-date information or source links.
- The answer depends on current online content rather than local state.

Do not use this skill for:

- tracking or perception turns
- Feishu notification turns
- questions answerable from local session state alone

## Rules

1. Resolve the active session first.
2. In this runtime, prefer `ROBOT_AGENT_SESSION_ID` and `ROBOT_AGENT_STATE_ROOT` from the environment over hardcoded runtime paths.
3. Decide whether this turn really needs current online search.
4. If yes, call the bundled search helper once.
5. After the helper returns, answer the user naturally and stop.

## Helper Script

Use this deterministic helper:

- `python ./skills/web-search/scripts/search_turn.py --session-id <session-id> --state-root ./.runtime/agent-runtime --env-file .ENV --query ...`
- In the normal PI runtime, prefer:
  `python ./skills/web-search/scripts/search_turn.py --session-id "$ROBOT_AGENT_SESSION_ID" --state-root "$ROBOT_AGENT_STATE_ROOT" --env-file .ENV --query "..."`

Important:

- Keep the query short and focused.
- The helper is only a thin entrypoint; backend turn logic assembles and applies the processed payload.
- Do not inspect files, do not verify artifacts, and do not widen the turn beyond one search.
- Do not expose helper JSON to the user.
- Do not inspect files, do not verify artifacts, and do not call extra tools after the helper returns.
- Do not run follow-up searches unless the user explicitly asks for refinement.

## Output Contract

For handled turns:

1. choose this skill
2. call exactly one helper command
3. answer the user naturally from the helper result
4. stop immediately after answering
