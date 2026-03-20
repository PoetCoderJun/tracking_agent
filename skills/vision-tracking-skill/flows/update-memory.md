# Update Memory Flow

Use this flow after every localization attempt.

## Inputs

- previous tracking memory
- Main Agent locate result
- current frame batch

## Actions

1. Rewrite the memory as one compact paragraph.
2. Start from the previous tracking memory instead of drafting from scratch.
3. Preserve earlier details when they still appear valid, then add new stable target cues from the latest visual evidence.
4. Do not compress valid old detail into a shorter summary just for brevity; prefer expanding stable cues when new evidence refines them.
5. Prefer top-to-bottom appearance detail: hair and visible facial traits, upper-body clothing, lower-body clothing, shoes, body build, bags, and accessories.
6. Refresh how to distinguish the target from nearby people, especially the most confusable nearby candidates, using fine-grained appearance differences.
7. Keep uncertainty tentative. Do not rewrite guesses as facts.
8. Assume future frames may contain turning, arbitrary pose, partial-body crops, back view, or occlusion, so keep multiple backup cues instead of a single anchor feature.
9. Preserve cues that survive viewpoint change and partial visibility, and explicitly favor contrastive details against the most confusable nearby person.
10. Do not use action, pose, or transient location as the main identity cue inside memory.
11. Rewrite in place. Do not append raw logs.

## Runtime mapping

- Skill sub-agent prompt for memory rewriting
- `SessionStore.write_memory(...)`
- `scripts/memory_rewriter.py` to normalize the rewritten memory before saving
