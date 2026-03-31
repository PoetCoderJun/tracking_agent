# Memory Format

The canonical tracking memory content is a small JSON object.

The skill uses two layers:

- Model output: one JSON object with fixed fields
- Stored file: the runtime persists that JSON object under `skill_cache["tracking"]["latest_memory"]`

The JSON object is the real contract. Any formatted text shown in the viewer is a presentation detail.

## Rules

- Use this fixed shape:
  - `appearance.head_face`
  - `appearance.upper_body`
  - `appearance.lower_body`
  - `appearance.shoes`
  - `appearance.accessories`
  - `appearance.body_shape`
  - `distinguish`
  - `summary`
- Each value must be a string.
- Keep the object optimized for the next search turn, but do not drop useful stable appearance details only to make it shorter.
- Start from the existing memory each round, preserve details that still appear valid, and only update the body parts that are visible in the latest target crop and frame.
- If a body part is not visible or not reliable in the latest image, keep the old value instead of clearing it.
- Prioritize stable local appearance cues: hair, visible facial traits, eyewear or mask, upper-body clothing, lower-body clothing, shoes, body build, bags, and accessories.
- When nearby people look similar, refine to small but stable differences such as sleeve length, collar shape, logo, stripe placement, hem length, shoe sole color, strap side, or face-framing hair.
- `distinguish` should be concise. Fill it only when the current frame contains a genuinely confusing person.
- If there is no obvious confusing person in the current frame, keep `distinguish` as an empty string.
- When `distinguish` is used, directly describe the confusing person's stable features and the target's distinguishing cues against that person. Avoid filler such as location, direction, or generic future reminders.
- Keep `summary` target-only. Put confusion handling and person-to-person comparison in `distinguish`, not in `summary`.
- Assume the person may be visible only from the upper body, lower body, back, or a partially occluded crop.
- Do not rely on any single feature alone; preserve multiple local appearance cues that can still work when one or two cues disappear.
- Treat invisible cues as temporarily unknown rather than disproven.
- Do not store actions, pose, transient location, bbox IDs, or confirmation state in the memory.

## Stored JSON Example

```json
{
  "appearance": {
    "head_face": "黑色偏短直发，额前有刘海，脸型偏窄，戴细框眼镜。",
    "upper_body": "浅灰圆领短袖上衣，胸前有小块深色图案，版型偏直。",
    "lower_body": "深色直筒长裤，裤型不贴腿。",
    "shoes": "深色运动鞋，白色鞋底较厚。",
    "accessories": "单肩包，包带落在右肩。",
    "body_shape": "体型偏瘦，肩较窄。"
  },
  "distinguish": "相似人：浅色上衣、无眼镜、上衣更纯净；目标区别：细框眼镜、右肩包带、胸前小块深色图案，若只看下半身再看直筒长裤和厚白鞋底。",
  "summary": "短发、细框眼镜、浅灰短袖上衣、深色直筒长裤、厚白鞋底深色运动鞋，右肩单肩包。"
}
```
