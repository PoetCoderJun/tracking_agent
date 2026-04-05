# Output Contracts

## Final Turn Payload

The skill must return one raw JSON object:

```json
{
  "status": "idle" | "processed",
  "skill_name": string | null,
  "session_result": object | null,
  "latest_result_patch": object | null,
  "skill_state_patch": object | null,
  "user_preferences_patch": object | null,
  "environment_map_patch": object | null,
  "perception_cache_patch": object | null,
  "robot_response": object | null,
  "tool": "init" | null,
  "tool_output": object | null,
  "rewrite_output": object | null,
  "rewrite_memory_input": object | null,
  "reason": string | null
}
```

Notes:

- This skill is only for selecting one current candidate person.
- `session_result` is the minimal final result for the target-selection turn.
- `skill_state_patch` only updates tracking-owned fields under `skill_cache["tracking"]`.
- For processed turns from this skill, set `tool` to `init`.
- Keep canonical names such as `target_id`, `bounding_box_id`, `found`, and `text`.

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
