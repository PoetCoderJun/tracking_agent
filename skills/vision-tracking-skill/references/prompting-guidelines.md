# Prompting Guidelines

## Main principles

- VLM is the primary decision-maker.
- The current memory is search context, not a source of unquestioned truth.
- The newest frame is the output frame for bbox coordinates.
- History frames are supporting context, but identity matching should still rely primarily on stable appearance.
- The canonical output shapes live in [output-contracts.md](./output-contracts.md).
- The canonical memory-writing rules live in [memory-format.md](./memory-format.md).

## Human-in-the-loop

- Use the user's initial description as rough grounding.
- If ambiguity remains, ask one focused clarification question.
- Clarification should narrow by distinguishing appearance first, and only use static spatial relations as secondary support when needed.
- Free-form chat should answer from memory and recent frames without resetting the session.

## Localization heuristics

- Prefer candidates that remain consistent across multiple stable cue groups.
- Avoid single-cue matching, especially in side-by-side or crossing cases.
- Treat currently invisible cues as unknown, not as negative evidence.
- Do not use action, pose, gait, temporary orientation, or instantaneous location as the main identifying cue.
- Phrase uncertainty as tentative hypotheses.

## Auxiliary signals

- Edge-side hints may be included as weak priors.
- ReID is optional weak evidence only in this MVP.
- Identity-level face recognition is excluded from this MVP, but visible facial traits may be used as ordinary appearance evidence.
