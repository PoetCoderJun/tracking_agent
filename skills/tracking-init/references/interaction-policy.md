# Interaction Policy

This skill is a single-turn target-selection skill over persistent state.
It is the `tracking-init` skill surface, not the continuous tracking runtime.

## Core rule

Do not force every message into this skill.

Use this skill only when the user is identifying which current candidate person should become the target.

Natural-language requests like `请跟踪穿黑衣服的人` should be treated as target-selection requests.
If the request is a clear bind/init request, the first tool action should be the tracking helper.
Do not inspect repository files or runtime directories before deciding whether this skill applies.
If this runtime already provides `ROBOT_AGENT_SESSION_ID` / `ROBOT_AGENT_STATE_ROOT`, use them directly instead of discovering the active session by reading `.runtime` or echoing env vars first.
If you need the current visual, read `$ROBOT_AGENT_STATE_ROOT/perception/latest_frame.jpg` directly; do not read `snapshot.json` first only to recover the image path.

## For each applicable user message

1. Decide whether the turn is bind/init, ambiguous, or lifecycle/status.
2. For a clear bind/init request, call the tracking helper immediately.
3. For an ambiguous request, ask one focused clarification question about stable appearance differences.
4. For lifecycle/status/continuation requests, do not use init.

## Common but non-exhaustive moves

- bind the first target from the current candidate boxes
- replace the target with another visible candidate
- accept an explicit candidate ID
- reject an invalid candidate ID with clarification
- ask for one more stable appearance detail

These are examples, not a closed taxonomy.

## Human-in-the-loop principle

The user is allowed to refine or replace the target at any time.

The agent should adapt naturally:

- confirm a target when the current evidence is sufficient
- ask one focused clarification when ambiguity remains
- reject invalid candidate IDs explicitly
- avoid inventing candidates that are not in the current candidate set

## Tooling principle

This skill should only call backend `init` for deterministic execution.

It should not handle:

- lifecycle control
- long-running tracking control
- status/explanation turns
- memory rewrite
