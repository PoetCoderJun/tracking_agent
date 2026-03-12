# Answer Chat Flow

Use this flow when the user asks a tracking-related question during an active session.

## Example questions

- Where did this person go?
- Why do you think this is still the same target?
- What are the main distractors right now?

## Actions

1. Answer from the current memory and the latest frame batch.
2. Keep the answer concise and explicit about uncertainty.
3. Do not reset the target or rewrite the session unless the user explicitly asks to do so.

## Runtime mapping

- `scripts/session_store.py --show-memory` to inspect current memory before answering
- `scripts/answer_tracking_chat.py` to produce the grounded answer
