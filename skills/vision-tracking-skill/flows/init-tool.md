# Init Tool Flow

Use this tool flow when the host agent should call `init` to start tracking or replace the target.

## Actions

1. Treat the user description as rough grounding, not a complete identity profile.
2. Select only from the provided candidate `bounding_box_id` values.
3. Prefer stable appearance evidence over action, pose, or temporary position.
4. If more than one candidate remains plausible, ask one focused clarification question instead of guessing.
5. If initialization succeeds, persist the target crop and write the first memory paragraph using [memory-format.md](../references/memory-format.md).

## Runtime mapping

- main runtime: `scripts/pi_backend_bridge.py --tool init` to execute the backend-connected init turn end to end
- direct adapter path: `scripts/pi_agent_adapter.py invoke --tool init` to run init against a prepared context file
- integration harness: `scripts/track_from_description.py` drives the first-frame init pass and calls `scripts/main_agent_locate.py`
- skill prompt and output contract from [output-contracts.md](../references/output-contracts.md)
