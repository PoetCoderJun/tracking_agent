# Prompting Guidelines

## Main principles

- VLM is the primary decision-maker.
- The current memory is search context, not a source of unquestioned truth.
- The newest frame is the output frame for bbox coordinates.
- History frames are temporal context for movement and disappearance reasoning.

## Human-in-the-loop

- Use the user's initial description as rough grounding.
- If ambiguity remains, ask one focused clarification question.
- Clarification should narrow by position, motion, or distinguishing appearance.
- Free-form chat should answer from memory and recent frames without resetting the session.

## Memory update rules

- Rewrite in place instead of appending logs.
- Keep stable target cues when they remain useful.
- Use one short paragraph instead of sectioned memory.
- Focus on two things only: target description and how to distinguish the target from nearby people.
- Phrase uncertainty as tentative hypotheses.

## Auxiliary signals

- Edge-side hints may be included as weak priors.
- ReID is optional weak evidence only in this MVP.
- Face is excluded from this MVP.
