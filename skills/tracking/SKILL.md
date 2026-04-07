---
name: tracking
description: Use when one turn needs to identify which current candidate person the user is pointing at.
---

# Tracking Skill

## Overview

This skill only does one thing: identify which current candidate person the user means.

- The agent runner should read context, think, inspect state, and decide whether this skill applies.
- If it applies, the skill should help confirm one person.
- This is a one-shot target-selection skill.

## When to Use

- The user is defining the target person.
- The user is replacing the current target with another person.
- The user explicitly names a candidate ID such as `跟踪 ID 为 N` or `切换到 ID N`.
- The turn depends on the current candidate boxes in the latest frame.

Do not use this skill for:

- lifecycle control turns
- status/explanation turns
- long-running daemon or polling work

## Quick Reference

| Situation | Preferred move |
| --- | --- |
| User defines or replaces a target | reason in skill, then call backend `init` |
| User explicitly says `跟踪 ID 为 N` / `切换到 ID N` | reason in skill, then call backend `init` |
| Explicit candidate ID is invalid | processed clarification |

## Routing Rules

1. Read `turn_context.json` first.
2. Read `context_paths.route_context_path`.
3. If this skill applies and you need grounded state, read `state_paths.session_path`.
4. Decide only whether the user is selecting one person from the current candidate set.
5. If yes, call the backend `init` command and return its stdout unchanged.
6. If not, do not force the turn into this skill.
7. If the route context is insufficient, read `state_paths.session_path` only as needed to decide whether target selection applies.
8. Do not fetch extra perception metadata unless the deterministic backend command needs it internally.

## What To Read

- `turn_context.json`
- `context_paths.route_context_path`
- `state_paths.session_path` when you need grounded state

Do not read extra references or raw persisted state unless you are blocked.

## Tool Rules

### Agent Reasoning

- Use this skill only for target selection.
- The skill should decide after reading context. Do not rely on backend pre-routing heuristics inside chat turns.
- If the user has not yet given enough stable appearance evidence, ask one focused clarification question.

### Backend Command

- When this skill applies, call backend `init`.
- Return the backend command output unchanged.
- Do not call backend helper modules directly from this skill.

## Helper Scripts

Use this backend deterministic command:

- `python -m backend.tracking.cli init --session-file <session.json> --target-description ... --env-file <env> --artifacts-root <artifacts>`

Important:

- This backend command already performs deterministic person selection and assembles the final JSON payload expected by the runner.
- When you use this backend command, return its stdout as the final answer without rewriting fields by hand.
- Do not call backend helper modules such as `backend.tracking.select` directly from the skill for ordinary target selection turns.

## Output Contract

Before returning, read [output-contracts.md](./references/output-contracts.md).

For target-selection turns:

1. decide that the user is selecting one person
2. call exactly one backend `init` command
3. return that command's JSON unchanged

For ambiguity:

1. keep the turn processed
2. ask one focused clarification question about stable appearance differences

## Canonical References

- [output-contracts.md](./references/output-contracts.md)

## Common Mistakes

- Mixing target selection with unrelated turn types.
- Calling backend helper modules manually when the backend `init` command already does the orchestration.
- Rewriting the final JSON by hand after the backend `init` command has already returned it.
