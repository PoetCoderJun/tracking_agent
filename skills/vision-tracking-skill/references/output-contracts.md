# Output Contracts

## Main Agent locate result

```json
{
  "found": true,
  "bbox": [x1, y1, x2, y2],
  "confidence": 0.86,
  "reason": "brief explanation",
  "autonomous_inference": null,
  "needs_clarification": false,
  "clarification_question": null
}
```

When the target is not found:

```json
{
  "found": false,
  "bbox": null,
  "confidence": 0.31,
  "reason": "why the target is not confidently visible",
  "autonomous_inference": {
    "likely_whereabouts": ["may have moved behind the left corner"],
    "likely_action": "continued moving toward the corridor",
    "priority_search_regions": ["left corridor exit", "corner reappearance area"]
  },
  "needs_clarification": false,
  "clarification_question": null
}
```

When ambiguity remains:

```json
{
  "found": false,
  "bbox": null,
  "confidence": 0.36,
  "reason": "multiple candidates remain plausible",
  "autonomous_inference": {
    "likely_whereabouts": ["near the left doorway"],
    "likely_action": "continued moving left",
    "priority_search_regions": ["left doorway", "left corner"]
  },
  "needs_clarification": true,
  "clarification_question": "Do you mean the person nearer the door or the one in the middle?"
}
```

## Session status values

- `initialized`
- `tracked`
- `missing`
- `clarifying`
