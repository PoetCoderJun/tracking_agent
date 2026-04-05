# Interaction Policy

This skill is a single-turn target-selection skill over persistent state.

## Core rule

Do not force every message into this skill.

Use this skill only when the user is identifying which current candidate person should become the target.

## For each applicable user message

1. Read the current turn context.
2. Inspect the latest candidate set and the active session state when needed.
3. Interpret the message as a target-selection request.
4. Decide whether the current evidence is sufficient to identify one person.
5. If yes, call backend `init`.
6. If not, ask one focused clarification question about stable appearance differences.

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
- status/explanation turns
- long-running tracking control
- memory rewrite
- long-running tracking control
