---
name: tracking
description: Use when one turn asks the robot to start or replace tracking for one visible person, whether by natural-language appearance description or explicit candidate ID.
---

# Tracking Skill

## Overview

This skill only does one thing: identify which current candidate person the user means.

- Use it when the user is defining or replacing the tracked person.
- This is a one-shot target-selection skill.
- It is not for long-running continuation or polling; those stay in the runtime loop.
- Natural-language requests such as `请跟踪穿黑衣服的人` and `跟踪前面那个黑衣服的人` belong here.
- Do not inspect repository files, runtime directories, or explain the codebase before deciding whether this skill applies.
- In this runtime, `ROBOT_AGENT_SESSION_ID` and `ROBOT_AGENT_STATE_ROOT` are already available. Do not browse `.runtime` just to find the active session.

## When to Use

- The user is defining the target person.
- The user is replacing the current target with another person.
- The user explicitly names a candidate ID such as `跟踪 ID 为 N` or `切换到 ID N`.
- The user points out one visible person by appearance, position, or distinguishing description such as `请跟踪穿黑衣服的人`.
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
| User says `请跟踪穿黑衣服的人` / `跟踪前面那个黑衣服的人` | reason briefly, then call backend `tracking-init` |
| Explicit candidate ID is invalid | processed clarification |

## Rules

0. Resolve the active session first if you were not given an explicit session id.
1. In this repo, prefer the already-exported env vars `ROBOT_AGENT_SESSION_ID` and `ROBOT_AGENT_STATE_ROOT` over manual runtime inspection.
2. Decide only whether the user is selecting one person from the current candidate set.
3. For natural-language tracking requests, do not start with repo/runtime inspection; make the routing decision from the user request plus the current visible candidate set.
4. If yes, call the backend `tracking-init` command exactly once as your first tool action.
5. Return the backend command output unchanged.
6. If not, do not force the turn into this skill.
7. If the user has not given enough stable appearance evidence, ask one focused clarification question.

## Helper Command

Use this backend deterministic command:

- `python -m backend.cli tracking-init --session-id <session-id> --state-root ./.runtime/agent-runtime --artifacts-root ./.runtime/pi-agent --text ...`
- In the normal PI runtime, prefer:
  `python -m backend.cli tracking-init --session-id "$ROBOT_AGENT_SESSION_ID" --state-root "$ROBOT_AGENT_STATE_ROOT" --artifacts-root ./.runtime/pi-agent --text "..."`

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
- Treating a natural-language tracking request as a code-analysis task.
- Reading `.runtime` or repository files before making the first routing decision for a natural-language tracking request.
- Calling backend helper modules manually when the backend command already performs deterministic selection.
- Rewriting the final JSON by hand after the backend command has already returned it.
