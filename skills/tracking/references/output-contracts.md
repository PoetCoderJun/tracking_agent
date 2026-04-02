# Output Contracts

## Final Turn Payload

Pi must return one raw JSON object:

```json
{
  "status": "idle" | "processed",
  "skill_name": "tracking" | null,
  "session_result": object | null,
  "latest_result_patch": object | null,
  "skill_state_patch": object | null,
  "user_preferences_patch": object | null,
  "environment_map_patch": object | null,
  "perception_cache_patch": object | null,
  "robot_response": object | null,
  "tool": "reply" | "init" | "track" | "reset_context" | null,
  "tool_output": object | null,
  "rewrite_output": object | null,
  "rewrite_memory_input": object | null,
  "reason": string | null
}
```

Notes:

- `session_result` is the final tracking result for this turn.
- `skill_state_patch` only updates tracking-owned fields under `skill_cache["tracking"]`.
- `robot_response` should be grounded in the final turn result, not in helper output alone.
- For deterministic `track` turns, prefer `robot_response.action` as one of `track`, `ask`, or `wait`.
- `rewrite_memory_input` is optional follow-up work for the runner.
- For `init`, the runner may execute `rewrite_memory_input` asynchronously after the target has already been confirmed and bound.
- For `track`, the runner may execute `rewrite_memory_input` asynchronously after the main turn has already completed.
- `session_result` must be a minimal turn result, never a raw session snapshot.
- Keep canonical names such as `target_id`, `bounding_box_id`, `found`, and `text`. Do not replace them with ad-hoc names such as `candidate_id`, `action_taken`, `target_confirmed`, or `position_analysis`.
- For processed turns, set `tool` to `reply`, `init`, or `track`.

## Canonical `session_result` Shapes

### `reply`

Use this for grounded tracking chat, including:
- `他现在在哪里`
- `现在在左边还是右边`
- `还在跟踪同一个人吗`
- `当前候选人的 ID 是什么`

```json
{
  "behavior": "reply",
  "frame_id": "frame_000123",
  "target_id": 12,
  "bounding_box_id": 12,
  "found": true,
  "text": "目标仍然是 ID 为 12 的人，最近一帧位置为 [x1, y1, x2, y2]。",
  "reason": "brief explanation"
}
```

### `init` or `track` Success

```json
{
  "behavior": "init" | "track",
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
  "action": "track",
  "target_id": 12,
  "text": "已确认跟踪 ID 为 12 的目标。"
}
```

### Clarification

Use this when ambiguity remains or when the user explicitly names an invalid candidate ID. This is still a processed tracking turn, not `idle`.

```json
{
  "behavior": "init" | "track" | "reply",
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

Notes:

- If the user explicitly asked to track a candidate ID and that ID is missing, prefer `behavior: "init"` and `tool: "init"`.
- Keep `found: false`; do not silently convert the turn into a plain chat answer.
- Copy the same clarification into both `clarification_question` and `text`.
- Include `available_targets` only as optional support, never as a substitute for `found=false` and `clarification_question`.

Recommended `robot_response`:

```json
{
  "action": "ask",
  "question": "当前画面里没有 ID 为 99 的候选人，请确认目标 ID。",
  "text": "当前画面里没有 ID 为 99 的候选人，请确认目标 ID。"
}
```

### Deterministic Wait

Use this when the deterministic matcher is uncertain and should do nothing this turn.

```json
{
  "behavior": "track",
  "frame_id": "frame_000123",
  "target_id": 12,
  "bounding_box_id": 12,
  "found": false,
  "decision": "wait",
  "text": "当前不确定，保持等待。",
  "reason": "最佳候选分数过低（score=0.611）。"
}
```

Recommended `robot_response`:

```json
{
  "action": "wait",
  "text": "当前不确定，保持等待。"
}
```

### `skill_state_patch`

Only include tracking-owned fields directly under `skill_cache["tracking"]`:

```json
{
  "latest_target_id": 12,
  "latest_confirmed_frame_path": "/abs/path/to/frame.jpg",
  "latest_target_crop": "/abs/path/to/crop.jpg",
  "latest_front_target_crop": "/abs/path/to/front-crop.jpg",
  "latest_back_target_crop": "/abs/path/to/back-crop.jpg",
  "latest_memory": {
    "core": "...",
    "front_view": "...",
    "back_view": "...",
    "distinguish": "..."
  },
  "target_description": "黑衣服的人",
  "pending_question": null
}
```

Do not wrap these fields again under `"tracking": {...}`.

## `select_target.py` Output

```json
{
  "behavior": "init" | "track",
  "text": "给用户的简短回复",
  "frame_id": "frame_000123",
  "target_id": 12,
  "bounding_box_id": 12,
  "found": true,
  "needs_clarification": false,
  "clarification_question": null,
  "pending_question": null,
  "memory": "上一次 tracking memory 的展示文本",
  "reason": "brief explanation",
  "reject_reason": "仅在 wait 时填写的拒绝绑定理由，否则为空字符串",
  "latest_target_crop": "/abs/path/to/crop.jpg",
  "target_description": "用户描述",
  "reset_reference_crops": false,
  "rewrite_memory_input": {
    "task": "init" | "update",
    "crop_path": "/abs/path/to/crop.jpg",
    "frame_paths": ["/abs/path/to/frame.jpg"],
    "frame_id": "frame_000123",
    "target_id": 12
  },
  "elapsed_seconds": 0.12
}
```

When ambiguity remains, keep `found=false`, set `needs_clarification=true`, and fill `clarification_question`.

When the user explicitly names an invalid candidate ID, this helper already returns the canonical clarification shape. Prefer using that result directly instead of paraphrasing it into a looser chat-only payload.

## `rewrite_memory.py` Output

```json
{
  "task": "init" | "update",
  "memory": {
    "core": "...",
    "front_view": "...",
    "back_view": "...",
    "distinguish": "..."
  },
  "frame_id": "frame_000123",
  "target_id": 12,
  "crop_path": "/abs/path/to/crop.jpg",
  "reference_view": "front" | "back" | "unknown",
  "elapsed_seconds": 0.08
}
```

## `rewrite_memory_input`

This is optional top-level follow-up work returned by deterministic `init` or `track` scripts.

```json
{
  "task": "init" | "update",
  "crop_path": "/abs/path/to/crop.jpg",
  "frame_paths": ["/abs/path/to/frame.jpg"],
  "frame_id": "frame_000123",
  "target_id": 12
}
```

- For `task="init"`, the runner may execute this asynchronously after the target is already confirmed and bound.
- For `task="update"`, the runner may execute this asynchronously after the main turn has already completed.
