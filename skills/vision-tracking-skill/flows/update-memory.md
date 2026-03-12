# Update Memory Flow

Use this flow after every localization attempt.

## Inputs

- previous tracking memory
- Main Agent locate result
- current frame batch

## Actions

1. Rewrite the memory as one short paragraph.
2. First refresh the target description using the latest visual evidence.
3. Then refresh how to distinguish the target from nearby people.
4. Keep uncertainty tentative. Do not rewrite guesses as facts.
5. Rewrite in place. Do not append raw logs.

## Runtime mapping

- Skill sub-agent prompt for memory rewriting
- `SessionStore.write_memory(...)`
- `scripts/memory_rewriter.py` to normalize the rewritten memory before saving
