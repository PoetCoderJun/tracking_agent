# Prompting Guidelines

## Main principles

- VLM is the primary decision-maker.
- The current memory is search context, not a source of unquestioned truth.
- The newest frame is the output frame for bbox coordinates.
- History frames are supporting context, but identity matching should still rely primarily on stable appearance.

## Human-in-the-loop

- Use the user's initial description as rough grounding.
- If ambiguity remains, ask one focused clarification question.
- Clarification should narrow by distinguishing appearance first, and only use static spatial relations as secondary support when needed.
- Free-form chat should answer from memory and recent frames without resetting the session.

## Memory update rules

- Rewrite in place instead of appending logs.
- Keep stable target cues when they remain useful, and prefer adding new detail over deleting old detail.
- Use one compact paragraph instead of sectioned memory.
- Do not shorten memory just to make it neat; for tracking, richer stable appearance detail is usually better than a terse summary.
- Focus on two things only: detailed target appearance and how to distinguish the target from nearby people.
- Prefer top-to-bottom appearance descriptions: hair and visible facial traits, upper-body clothing, lower-body clothing, shoes, body build, bags, and accessories.
- Assume future frames may show arbitrary pose, turning, partial body crops, back view, or occlusion.
- Avoid single-cue matching; use several stable appearance cues that can back each other up.
- Treat currently invisible cues as unknown, not as negative evidence.
- For continuous tracking, prefer candidates that remain consistent across multiple cue groups; do not switch identities based on one newly visible weak cue.
- Do not use action, pose, gait, temporary orientation, or instantaneous location as the main identifying cue.
- Phrase uncertainty as tentative hypotheses.

## Auxiliary signals

- Edge-side hints may be included as weak priors.
- ReID is optional weak evidence only in this MVP.
- Identity-level face recognition is excluded from this MVP, but visible facial traits may be used as ordinary appearance evidence.
