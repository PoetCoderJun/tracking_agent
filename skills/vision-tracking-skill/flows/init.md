# Init Flow

Use this flow when the user starts a tracking session or replaces the target.

## Inputs

- short user description of the target
- first frame, or the current query batch if initialization is happening mid-session
- candidate detections for the newest frame, each with a stable bounding box ID

## Actions

1. Treat the user description as rough grounding, not as a complete identity profile.
2. Select the correct `bounding_box_id` only from the provided candidates, then resolve that ID back to the local bbox for downstream crop generation.
3. Keep the first memory concise. It should only contain the cues that will help the next localization call.
4. If the target is ambiguous in the first frame, ask a focused clarification question before confirming the session.

## Runtime mapping

- Skill agent prompt for first-turn localization and first memory draft
- `scripts/session_store.py` to inspect/reset session artifacts
- `scripts/target_crop.py` to persist the confirmed target crop
- `scripts/bbox_visualization.py` to persist the first bbox preview
- `scripts/runtime_state.py --action reuse` if initialization reuses the current batch
