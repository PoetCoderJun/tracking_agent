---
name: tracking
description: Use when one turn needs to identify which current candidate person the user means and bind tracking to that person.
---

# Tracking Skill

## Overview

This skill only does one thing: identify which current candidate person the user means.

- Use it when the user is defining or replacing the tracked person.
- This is a one-shot target-selection skill.
- It is not for long-running continuation or polling; those stay in the runtime loop.

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
| User defines or replaces a target | reason briefly, then call backend `tracking-init` |
| User explicitly says `跟踪 ID 为 N` / `切换到 ID N` | reason briefly, then call backend `tracking-init` |
| Explicit candidate ID is invalid | processed clarification |

## Rules

0. Resolve the active session first if you were not given an explicit session id.
1. Decide only whether the user is selecting one person from the current candidate set.
2. If yes, call the backend `tracking-init` command exactly once.
3. Return the backend command output unchanged.
4. If not, do not force the turn into this skill.
5. If the user has not given enough stable appearance evidence, ask one focused clarification question.

## Helper Command

Use this backend deterministic command:

- `python -m backend.cli tracking-init --session-id <session-id> --state-root ./.runtime/agent-runtime --artifacts-root ./.runtime/pi-agent --text ...`

Important:

- This command already performs deterministic person selection and assembles the final JSON payload expected by the runtime.
- Do not call backend helper modules such as `backend.tracking.select` directly.
- Do not rewrite the final JSON by hand after the backend command returns it.

## Output Contract

For target-selection turns:

1. decide that the user is selecting one person
2. call exactly one backend `tracking-init` command
3. return its JSON unchanged

For ambiguity:

1. keep the turn processed
2. ask one focused clarification question about stable appearance differences

## Canonical References

- [output-contracts.md](./references/output-contracts.md)

## Common Mistakes

- Mixing target selection with unrelated turn types.
- Calling backend helper modules manually when the backend command already performs deterministic selection.
- Rewriting the final JSON by hand after the backend command has already returned it.
