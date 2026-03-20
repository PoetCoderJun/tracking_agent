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
4. Match candidates primarily through stable appearance details, not through action, pose, or transient position.
5. Assume the target may appear in arbitrary pose or only as a partial crop, so cross-check multiple stable cues instead of relying on a single visible trait.
6. Treat cues that are currently not visible as unknown instead of immediate contradiction.
7. In confusing side-by-side cases, avoid identity switching unless one candidate matches multiple cue groups and the alternatives show strong conflicts.
8. If the target is not confidently visible, return `found=false`.
9. If more than one candidate remains plausible, return `needs_clarification=true` and ask one focused question about stable appearance differences.

## Runtime mapping

- Skill agent prompt for the locate call on the selected batch
- `scripts/output_validator.py` to validate the locate result
- `scripts/target_crop.py` to persist a new reference crop after locally resolving the selected ID back to its bbox
- `scripts/bbox_visualization.py` to persist the locally resolved bbox overlay
- `scripts/runtime_state.py --action advance` after consuming a new batch
