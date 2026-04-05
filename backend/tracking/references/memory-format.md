# Memory Format

The canonical tracking memory content is a small JSON object.

The skill uses two layers:

- Model output: one JSON object with fixed fields
- Stored file: the runtime persists that JSON object under `skill_cache["tracking"]["latest_memory"]`

The JSON object is the real contract. Any formatted text shown in the viewer is a presentation detail.

## Rules

- Use this fixed shape:
  - `core`
  - `front_view`
  - `back_view`
  - `distinguish`
- Each value must be a string.
- `core` stores cross-view identity cues that are likely to remain useful later.
- `front_view` stores a natural-language description of the person when seen from the front.
- `back_view` stores a natural-language description of the person when seen from the back.
- `distinguish` stores how to separate the target from the most similar confusing person in the current frame. If no clear confusing person exists, keep it empty. Only use stable appearance differences. Do not use actions, posture, hand state, gait, whether someone has hands in pockets, or similar changeable cues.
- Keep the object optimized for the next search turn, but do not drop useful stable appearance details only to make it shorter.
- Start from the existing memory each round, preserve details that still appear valid, and only update the views that are actually visible in the latest target crop and frame.
- If the current frame does not show the front, keep the old `front_view` instead of clearing it. Do the same for `back_view`.
- Let the model describe as much visible detail as possible from top to bottom; do not force it into body-part checklists.
- Prioritize stable appearance cues over scene cues. Do not store actions, pose, transient location, bbox IDs, or confirmation state in the memory.
- Treat invisible cues as temporarily unknown rather than disproven.

## Stored JSON Example

```json
{
  "core": "体型偏瘦，整体是浅灰上衣配深色直筒长裤和厚白鞋底运动鞋，右肩有单肩包。",
  "front_view": "正面看是黑色偏短直发，额前有刘海，脸型偏窄，戴细框眼镜。上身浅灰上衣前胸有小块深色图案，版型偏直。下身是深色直筒长裤，脚上是深色运动鞋配较厚的白色鞋底。",
  "back_view": "背面看头发较短，肩窄，后背整体较干净，没有大面积夸张图案，包带从右肩落下。裤型直，鞋底从后方看仍偏白且较厚。",
  "distinguish": "相似人A：两者都穿浅灰到深灰色系上衣和深色长裤；A 的上衣更纯净、无眼镜、没有右肩包带；目标的细框眼镜、前胸小块深色图案和右肩单肩包更明显；可以通过眼镜、胸前图案和包带明显区分。"
}
```
