# Interaction Policy

This skill is a single-turn tracking skill over persistent state, not a fixed intent classifier.

## Core rule

Do not force each user turn into a closed set of labels before thinking.

Instead, for every new user message:

1. Read the active raw session state, then inspect current memory, latest result, and the newest frame.
2. Interpret the new message in the context of the ongoing tracking session.
3. Decide what action would move the session forward with the least unnecessary rigidity.
4. Use the skill's own deterministic scripts as atomic helpers, not as a prewritten workflow.

## Common but non-exhaustive moves

- initialize or replace the target
- run the next localization step
- answer a tracking-related question
- record a clarification and reuse the current batch
- ask the user one focused follow-up question
- explain uncertainty or likely whereabouts without mutating the target

These are examples, not a closed taxonomy.

## Human-in-the-loop principle

The user is allowed to interrupt, redirect, question, refine, or replace the target at any time.

The agent should adapt naturally:

- answer when the user is asking
- continue tracking when the user is advancing the session
- treat short continuation commands such as `持续跟踪`, `继续跟踪`, and `continue tracking` as advancement, not as free-form chat
- narrow ambiguity when clarification is needed
- reset only when the user is clearly changing the target

## Tooling principle

The scripts under `skills/tracking/scripts/` are only deterministic helpers:

- read frames
- localize the target
- rewrite memory
- persist crops, bbox overlays, and session artifacts
- keep perception and optional loop processes alive

They should be used sparingly. Pi should still read state, decide the move, and write the final turn JSON itself.
