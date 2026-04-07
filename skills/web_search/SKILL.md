---
name: web_search
description: Use when the user needs current web information, links, or source-backed lookup results.
---

# Web Search Skill

## Overview

This skill handles current-information questions that require searching the web.

- The runner should still decide whether this skill applies on each turn.
- If it applies, the skill should perform a small web search and return a standard turn payload.
- This skill is for online lookup, not for local docs or robot perception.

## When to Use

- The user asks to search the web.
- The user asks for up-to-date information or source links.
- The answer depends on current online content rather than local state.

Do not use this skill for:

- tracking or perception turns
- Feishu notification turns
- questions answerable from local session state alone

## Routing Rules

1. Read `turn_context.json` first.
2. Read `context_paths.route_context_path`.
3. Decide whether this turn needs current online search.
4. If yes, call the bundled search helper, use its result, and answer the user naturally.
5. If no, do not force the turn into this skill.

## Helper Script

Use this deterministic helper:

- `python -m skills.web_search.scripts.search_turn --turn-context-file <turn_context.json> --query ...`

Important:

- The helper is an internal execution surface for obtaining search results.
- Keep the query short and focused.
- Do not expose the helper JSON to the user.
- After the helper returns, give the user a concise natural-language answer with sources when useful.
- After the helper returns and you have answered, stop immediately.
- Do not inspect files, do not verify artifacts, do not run follow-up searches, and do not call any more tools.

## Output Contract

For handled turns:

1. choose this skill
2. call exactly one helper command
3. answer the user naturally from the helper result
4. stop immediately after answering

If web search configuration is missing, the helper will still return a processed reply explaining the issue.
