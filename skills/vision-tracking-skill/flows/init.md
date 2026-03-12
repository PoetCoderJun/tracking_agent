# Init Flow

Use this flow when the user starts a tracking session or replaces the target.

## Inputs

- short user description of the target
- first frame, or the current query batch if initialization is happening mid-session

## Actions

1. Treat the user description as rough grounding, not as a complete identity profile.
2. Read the frame and write the first tracking memory using the fixed Markdown section titles from [memory-format.md](../references/memory-format.md).
3. Keep the first memory concise. It should only contain the cues that will help the next localization call.
4. If the target is ambiguous in the first frame, ask a focused clarification question before confirming the session.

## Runtime mapping

- Skill agent prompt for first-turn localization and first memory draft
- `scripts/session_store.py` to inspect/reset session artifacts
- `scripts/target_crop.py` to persist the confirmed target crop
- `scripts/bbox_visualization.py` to persist the first bbox preview
- `scripts/runtime_state.py --action reuse` if initialization reuses the current batch
