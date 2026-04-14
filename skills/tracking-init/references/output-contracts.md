# Output Contracts

## Final Turn Payload

The skill must return one raw JSON object. Use the same minimal processed-skill shell as other skills, then add tracking-specific fields only when they are actually needed.

```json
{
  "status": "processed",
  "skill_name": "tracking",
  "session_result": object,
  "tool": "init" | "track"
}
```

Notes:

- This skill is only for selecting one current candidate person.
- `session_result` is the minimal final result for the target-selection turn.
- `tool_output` may be included for debugging or downstream inspection.
- `robot_response` may be included when the caller needs a top-level action payload.
- `skill_state_patch` only updates tracking-owned fields under `state.capabilities["tracking-init"]`.
- `rewrite_memory_input` and `rewrite_output` are tracking-only extensions. Do not emit them unless the turn actually schedules or resolves memory rewrite work.
- Keep canonical names such as `target_id`, `bounding_box_id`, `found`, and `text`.

## Tracking Extensions

Add these fields only when needed:

```json
{
  "skill_state_patch": object,
  "robot_response": object,
  "tool_output": object,
  "rewrite_output": object,
  "rewrite_memory_input": object,
  "reason": "brief explanation"
}
```

## Canonical `session_result` Shapes

### Target Selected

```json
{
  "behavior": "init",
  "frame_id": "frame_000123",
  "target_id": 12,
  "bounding_box_id": 12,
  "found": true,
  "text": "已确认跟踪 ID 为 12 的目标。",
  "reason": "brief explanation",
  "latest_target_crop": "/abs/path/to/crop.jpg"
}
```

Recommended `robot_response`:

```json
{
  "action": "confirm",
  "target_id": 12,
  "text": "已确认跟踪 ID 为 12 的目标。"
}
```

### Clarification

Use this when ambiguity remains or when the user explicitly names an invalid candidate ID.

```json
{
  "behavior": "init",
  "frame_id": "frame_000123",
  "target_id": null,
  "bounding_box_id": null,
  "found": false,
  "needs_clarification": true,
  "clarification_question": "当前画面里没有 ID 为 99 的候选人，请确认目标 ID。",
  "text": "当前画面里没有 ID 为 99 的候选人，请确认目标 ID。",
  "reason": "brief explanation"
}
```

Recommended `robot_response`:

```json
{
  "action": "ask",
  "question": "当前画面里没有 ID 为 99 的候选人，请确认目标 ID。",
  "text": "当前画面里没有 ID 为 99 的候选人，请确认目标 ID。"
}
```

## `skill_state_patch`

Only include selection-owned fields directly under the persisted target-state namespace:

```json
{
  "latest_target_id": 12,
  "latest_confirmed_frame_path": "/abs/path/to/frame.jpg",
  "latest_target_crop": "/abs/path/to/crop.jpg",
  "latest_front_target_crop": "/abs/path/to/front-crop.jpg",
  "latest_back_target_crop": "/abs/path/to/back-crop.jpg",
  "target_description": "黑衣服的人",
  "pending_question": null
}
```

Do not wrap these fields again under another nested object.
