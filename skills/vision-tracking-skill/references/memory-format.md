# Memory Format

The tracking memory should be a single dense paragraph.

## Rules

- Do not split the memory into sections or bullet lists.
- Write one compact paragraph in natural language.
- Keep memory optimized for the next search turn, but do not drop useful stable appearance details only to make it shorter.
- Do not aggressively abbreviate or compress the description; when a stable cue is useful, prefer expanding it into a concrete phrase instead of replacing it with a short summary.
- Prefer revising the paragraph over appending logs.
- Start from the existing memory each round, preserve details that still appear valid, and add new stable cues when the latest evidence supports them.
- If an old detail remains useful, keep it and expand it when new evidence makes it more specific; only delete details that are clearly wrong, redundant, or no longer helpful.
- First describe the target's traits from top to bottom in as much useful detail as possible.
- Prioritize stable appearance cues: hair, visible facial traits, eyewear or mask, upper-body clothing, lower-body clothing, shoes, body build, bags, and accessories.
- When nearby people look similar, refine to small but stable differences such as sleeve length, collar shape, logo, stripe placement, hem length, shoe sole color, strap side, or face-framing hair.
- Assume the person may turn around, face sideways, bend down, or be visible only from the upper body, lower body, back, or a partially occluded crop.
- Do not rely on any single feature alone; preserve a bundle of stable cues that can still work when one or two cues disappear.
- Prefer cue bundles that survive viewpoint change, for example pants+shoe-sole+body build for low-angle views, or hair+collar+strap side for upper-body-only views.
- Treat invisible cues as temporarily unknown rather than disproven.
- Use actions, pose, temporary orientation, and transient location only as weak context, not as the main identifying basis.
- Then state how to distinguish the target from nearby people.
- Distinguish observations from hypotheses in wording.

## Example skeleton

```md
# Tracking Memory

黑色偏短直发，额前有刘海，脸型偏窄，戴细框眼镜，穿浅灰圆领短袖上衣、胸前有小块深色图案，深色直筒长裤，白色鞋底较厚的深色运动鞋，背单肩包且包带落在右肩，体型偏瘦、肩较窄。和周围相似人区分时优先看眼镜、右肩包带、上衣胸前小图案、裤型偏直和厚白鞋底。
```
