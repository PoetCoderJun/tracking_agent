# Output Contracts

## Main Agent locate result

```json
{
  "found": true,
  "bounding_box_id": 12,
  "reason": "brief explanation",
  "needs_clarification": false,
  "clarification_question": null
}
```

When the target is not found:

```json
{
  "found": false,
  "bounding_box_id": null,
  "reason": "why the target is not confidently visible",
  "needs_clarification": false,
  "clarification_question": null
}
```

When ambiguity remains:

```json
{
  "found": false,
  "bounding_box_id": null,
  "reason": "multiple candidates remain plausible",
  "needs_clarification": true,
  "clarification_question": "Do you mean the person nearer the door or the one in the middle?"
}
```

## Session status values

- `initialized`
- `tracked`
- `missing`
- `clarifying`
