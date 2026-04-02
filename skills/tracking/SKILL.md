---
name: tracking
description: Use when one turn needs grounded visual tracking over persisted session state, especially target initialization, continue-tracking, target switching by candidate ID, or grounded tracking Q&A on the active session.
---

# Tracking Skill

## Overview

This is a single-turn skill. It does not own the perception loop or the tracking runtime loop.

Pi should make one routing decision for the current turn, then use one deterministic entry script when the turn is `init` or `track`.

Semantic rule: `reply`, `init`, and `track` are turn types. The deterministic scripts already assemble the final payload for `init` and `track`.

## When to Use

- The current turn already has a persisted route context and, when tracking is enabled, a persisted tracking context.
- The user is selecting a person to track, continuing an active track, switching to a candidate ID, or asking a grounded question about the tracked person.
- The turn depends on `recent_frames`, candidate detections, tracking memory, or the active target ID.

Do not use this skill for:

- One-shot perception without session state.
- Identity recognition or face recognition.
- Owning any long-running daemon or polling loop.

## Quick Reference

| Situation | Preferred move |
| --- | --- |
| User defines or replaces a target | `init` |
| User explicitly says `跟踪 ID 为 N` / `切换到 ID N` | `init` |
| User sends `持续跟踪` / `继续跟踪` and an active target exists | `track` |
| User asks where the tracked person is, whether it is still the same person, or asks a grounded visual question | `reply` |
| Explicit candidate ID is invalid | processed clarification, usually through `init` |

## Routing Rules

1. Read `turn_context.json` first.
2. Read `context_paths.route_context_path`.
3. If you route into tracking, read `context_paths.tracking_context_path`.
4. Decide only which turn type applies: `reply`, `init`, or `track`.
5. If the turn type is `init` or `track`, call the deterministic entry script and return its stdout unchanged.
6. If the specialized context files are insufficient, prefer `service_commands.perception_read`.
7. Only if both specialized context files and the perception CLI output are insufficient may you fall back to raw persisted state.

## What To Read

- `turn_context.json`
- `context_paths.route_context_path`
- `context_paths.tracking_context_path` when the tracking skill is enabled

Do not read extra references or raw persisted state unless you are blocked.

## Tool Rules

### `init`

- Use this when the user defines a target, replaces a target, or explicitly names a candidate ID to follow.
- Do not hand-roll target selection in Pi.
- Always call the deterministic init script.

### `track`

- Use this for bare continuation commands such as `持续跟踪`, `继续跟踪`, or `continue tracking` when an active target already exists.
- Do not hand-roll target localization in Pi.
- Always call the deterministic track script.
- If the deterministic track script returns uncertainty, do not re-think the tracking turn inside Pi. Return the script output unchanged.

### `reply`

- Use this for grounded tracking Q&A.
- Keep the reply short and explicit about uncertainty.
- Do not call localization scripts for ordinary Q&A unless the user is actually advancing or switching the tracked target.

## Helper Scripts

Use these deterministic entry scripts for the fragile workflows:

- `python skills/tracking/scripts/run_tracking_init.py --tracking-context-file <tracking_context.json> --target-description ... --env-file <env> --artifacts-root <artifacts>`
- `python skills/tracking/scripts/run_tracking_track.py --tracking-context-file <tracking_context.json> --user-text ... --env-file <env> --artifacts-root <artifacts>`

Important:

- These scripts already call the lower-level helpers they need.
- These scripts already assemble the final JSON payload expected by the runner.
- When you use one of these scripts, return its stdout as the final answer without rewriting fields by hand.
- Do not call `skills/tracking/core/select.py` or `skills/tracking/scripts/rewrite_memory.py` directly from Pi for ordinary `init` or `track` turns.

The lower-level helper scripts still exist, but they are internal building blocks for the deterministic entry scripts:

- `python skills/tracking/core/select.py ...`
- `python skills/tracking/scripts/rewrite_memory.py ...`

`rewrite_memory.py` is not part of Pi routing anymore.

- For `init`, memory rewrite is off the critical path. The runner confirms and binds the target first, then schedules rewrite asynchronously in a detached subprocess worker.
- For `track`, memory rewrite is off the critical path. The runner schedules rewrite asynchronously in a detached subprocess worker.

## Output Contract

Before returning, read [output-contracts.md](./references/output-contracts.md).

For `init` or `track`:

1. route the turn
2. call exactly one deterministic entry script
3. return that script's JSON unchanged

For continuation uncertainty, the deterministic script should already decide between:

- `track`: continue following `target_id`
- `ask`: ask the user a concrete disambiguation question
- `wait`: model is uncertain, do nothing this turn

For `reply`:

1. answer directly
2. write the final JSON yourself using the reference contract

## Canonical References

- [output-contracts.md](./references/output-contracts.md)
- [memory-format.md](./references/memory-format.md)

## Common Mistakes

- Treating `init` or `track` as open-ended reasoning problems instead of fixed workflows.
- Calling `skills/tracking/core/select.py` and `skills/tracking/scripts/rewrite_memory.py` manually from Pi when the entry script already does the orchestration.
- Rewriting the final JSON by hand after a deterministic entry script has already returned it.
- Running memory rewrite inline on the critical path of `continue tracking`.
- Assuming `init` can finish successfully without producing initial tracking memory.
