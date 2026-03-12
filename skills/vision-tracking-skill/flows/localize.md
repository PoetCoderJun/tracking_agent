# Localize Flow

Use this flow for every low-frequency tracking turn.

## Inputs

- current batch of frames ordered from oldest to newest
- current tracking memory
- optional clarification notes from the user
- candidate detections for the newest frame, each with a stable bounding box ID and bbox

## Actions

1. Use the memory as search context, not as ground truth.
2. Return only the selected `bounding_box_id` for the newest frame in the batch.
3. Do not invent new boxes or coordinates outside the provided candidate list.
4. If the target is not confidently visible, return `found=false`.
5. If more than one candidate remains plausible, return `needs_clarification=true` and ask one focused question.

## Runtime mapping

- Skill agent prompt for the locate call on the selected batch
- `scripts/output_validator.py` to validate the locate result
- `scripts/target_crop.py` to persist a new reference crop after locally resolving the selected ID back to its bbox
- `scripts/bbox_visualization.py` to persist the locally resolved bbox overlay
- `scripts/runtime_state.py --action advance` after consuming a new batch
