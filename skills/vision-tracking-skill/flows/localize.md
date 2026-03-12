# Localize Flow

Use this flow for every low-frequency tracking turn.

## Inputs

- current batch of frames ordered from oldest to newest
- current tracking memory
- optional clarification notes from the user
- optional edge-side hint such as a tentative bbox or confidence

## Actions

1. Use the memory as search context, not as ground truth.
2. Return the bbox only for the newest frame in the batch.
3. If the target is not confidently visible, return `found=false` and provide `autonomous_inference`.
4. If more than one candidate remains plausible, return `needs_clarification=true` and ask one focused question.

## Runtime mapping

- Skill agent prompt for the locate call on the selected batch
- `scripts/output_validator.py` to validate the locate result
- `scripts/target_crop.py` to persist a new reference crop when found
- `scripts/bbox_visualization.py` to persist the bbox overlay
- `scripts/runtime_state.py --action advance` after consuming a new batch
