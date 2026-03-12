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

- `PiAgentCore.run_tracking_step(...)`
- `DashScopeTrackingBackend.locate_target(...)`
- `validate_locate_result(...)`
