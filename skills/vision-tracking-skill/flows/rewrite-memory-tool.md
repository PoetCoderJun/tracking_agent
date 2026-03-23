# Rewrite Memory Tool Flow

Use this tool flow when the host agent should call `rewrite_memory` after a successful `init` or `track`.

## Actions

1. Start from the previous memory instead of drafting from scratch.
2. Rewrite one dense paragraph using the canonical rules in [memory-format.md](../references/memory-format.md).
3. Preserve still-valid stable cues, add new stable evidence, and keep uncertainty tentative.
4. Do not append logs or optimize for brevity at the cost of search value.

## Runtime mapping

- main runtime: `scripts/pi_backend_bridge.py` starts the async rewrite worker after a successful `init` or `track`
- direct adapter path: `scripts/pi_agent_adapter.py invoke --tool rewrite_memory` to rewrite memory against a prepared context file
- integration harness: `scripts/track_from_description.py` calls `scripts/sub_agent_memory.py` and persists the resulting Markdown
- memory prompt and contract from [memory-format.md](../references/memory-format.md)
