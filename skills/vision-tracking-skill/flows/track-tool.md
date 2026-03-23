# Track Tool Flow

Use this tool flow when the host agent should call `track` on the latest batch for an already active target.

## Actions

1. Use memory as search context, not as unquestioned truth.
2. Return only the selected `bounding_box_id` for the newest frame. Never invent a new box.
3. Match primarily through stable appearance cues that can survive viewpoint change, partial visibility, and occlusion.
4. Treat currently invisible cues as unknown, not immediate contradiction.
5. If the target is not confidently visible, return `found=false`.
6. If multiple candidates remain plausible, return `needs_clarification=true` and ask one focused clarification question.

## Runtime mapping

- main runtime: `scripts/pi_backend_bridge.py --tool track` to execute one backend-connected tracking turn
- direct adapter path: `scripts/pi_agent_adapter.py invoke --tool track` to run track against a prepared context file
- integration harness: `scripts/track_from_description.py` advances batches and calls `scripts/main_agent_locate.py`
- skill prompt and output contract from [output-contracts.md](../references/output-contracts.md)
