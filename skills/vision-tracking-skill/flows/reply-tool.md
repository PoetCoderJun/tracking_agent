# Reply Tool Flow

Use this tool flow when the host agent should call `reply` for a tracking-related question or a clarification prompt.

## Example questions

- Where did this person go?
- Why do you think this is still the same target?
- What are the main distractors right now?

## Actions

1. Answer from the current memory and the latest frame batch.
2. Keep the answer concise and explicit about uncertainty.
3. Do not reset the target or rewrite memory unless the user explicitly asks for it.

## Runtime mapping

- main runtime: `scripts/pi_backend_bridge.py --tool reply` to answer against backend session context
- direct adapter path: `scripts/pi_agent_adapter.py invoke --tool reply` to answer against a prepared context file
