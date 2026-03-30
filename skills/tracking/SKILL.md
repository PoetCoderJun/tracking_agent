---
name: tracking
description: Use when one turn needs grounded visual tracking or grounded visual questions over persisted session state, including target selection, continue-tracking requests, position questions, same-target confirmations, or invalid candidate IDs that require clarification.
---

# Tracking Skill

## Overview

This is a single-turn skill. It does not own a loop, a daemon, or a backend service.

For each turn, the agent should read the latest persisted tracking state, decide the smallest useful move, and return one grounded reply or one tracking update. The skill may use its own deterministic scripts through Bash when needed, but orchestration stays in the agent.

Semantic rule: `reply`, `init`, `track`, and `rewrite_memory` are tools inside this skill, not standalone skills.

## When to Use

- The current session already has sampled frames and candidate detections on disk.
- The user is defining a target to track, continuing an active track, asking a tracking question, or correcting the current target.
- The user is asking a grounded visual question about the current tracked person or the latest frame, even if the wording sounds chatty.
- The user explicitly names a candidate ID, including an invalid ID that should produce clarification instead of `idle`.
- The agent needs to read `session.json`, `agent_memory.json`, recent frames, and the tracking portion of `skill_cache`.

Do not use this skill for:

- One-shot detection without session memory.
- Identity or face-recognition workflows.
- Long-running loops or perception daemons.

## Single-Turn Pattern

For one user turn:

1. Read persisted state first.
2. Interpret the latest user message in session context.
3. Choose the smallest next move: `init`, `track`, `reply`, or one focused clarification.
4. Use deterministic tracking tools only when they reduce ambiguity or perform concrete work.
5. Update tracking memory only after a successful `init` or `track`.

Read [interaction-policy.md](./references/interaction-policy.md) before combining tools.

## What To Read

- `turn_context.json`: provided by the runner for this turn; it tells you where the state files are
- `state_paths.session_path`: canonical session state, including `latest_result`, `conversation_history`, and `recent_frames`
- `state_paths.agent_memory_path`: canonical memory state, including `skill_cache["tracking"]`
- the newest frame image path from `recent_frames`
- the latest detections attached to that frame

## Quick Reference

| Situation | Preferred move |
| --- | --- |
| User defines or replaces a target | `init` |
| User explicitly says `跟踪 ID 为 N` / `切换到 ID N` | `init` and verify that ID with `select_target.py` |
| Active target should continue on the latest frame | `track` |
| User sends `持续跟踪` / `继续跟踪` | `track` |
| User asks a tracking question, visual question, or same-target confirmation | `reply` |
| User asks to track a non-existent candidate ID | `init` with clarification |
| Ambiguity remains | one focused clarification |
| `init` or `track` succeeds | `rewrite_memory` |

## Tool Rules

### `init`

- Treat the user description as rough grounding, not a complete identity profile.
- If the user explicitly names a candidate ID, always verify it with `select_target.py --mode init`. Do not freehand the answer from memory alone.
- An invalid explicit ID is still an `init` turn. Let the helper return `found=false` plus a clarification question.
- Select only from the candidate `bounding_box_id` values already present in the latest frame.
- Prefer stable appearance evidence over action, pose, or temporary position.
- If more than one candidate remains plausible, ask one focused clarification question instead of guessing.
- On success, persist the target crop and then rewrite memory.

### `track`

- Use memory as search context, not as unquestioned truth.
- Return only the selected `bounding_box_id` for the newest frame. Never invent a new box.
- Match primarily through stable appearance cues that can survive viewpoint change, partial visibility, and occlusion.
- Treat currently invisible cues as unknown, not immediate contradiction.
- If the target is not confidently visible, return `found=false`.
- If multiple candidates remain plausible, return one focused clarification question.

### `reply`

- Use this for tracking questions or clarification prompts.
- Use this for grounded visual chat such as `他现在在哪里`, `现在在左边还是右边`, `还在跟踪同一个人吗`, or `当前候选人的 ID 是什么`.
- Do not use `reply` for explicit target-selection commands such as `跟踪 ID 为 99 的人` or `切换到 ID 3`; those remain `init` turns and should verify the ID through `select_target.py`.
- Do not use it for bare continuation commands such as `持续跟踪`, `继续跟踪`, or `continue tracking` when an active target already exists.
- Answer from the current memory and the latest frame batch.
- Keep the answer concise and explicit about uncertainty.
- Do not reset the target or rewrite memory unless the user explicitly asks for it.

### `rewrite_memory`

- Use it after every successful `init` or `track`.
- Start from the previous memory instead of drafting from scratch.
- Rewrite one dense paragraph using the canonical rules in [memory-format.md](./references/memory-format.md).
- Preserve still-valid stable cues, add new stable evidence, and keep uncertainty tentative.

### Clarification

- Ask only one short, high-signal follow-up question.
- Focus on discriminating stable appearance traits first. Use static position only as secondary support.
- Store the clarification in the tracking skill state and let the next turn re-run localization with that clue.
- If the user explicitly names an invalid candidate ID, do not return `idle`; return a processed clarification turn.

## Helper Scripts

Only use helper scripts when the turn needs deterministic visual work that Pi should not hand-roll:

- `python skills/tracking/scripts/select_target.py --mode init --session-file <session.json> --memory-file <agent_memory.json> --target-description ...`
- `python skills/tracking/scripts/select_target.py --mode track --session-file <session.json> --memory-file <agent_memory.json> --user-text ...`
- `python skills/tracking/scripts/rewrite_memory.py --memory-file <agent_memory.json> --task <init|update> --crop-path ... --frame-path ... --frame-id ... --target-id ...`

For any turn that explicitly names a candidate ID, call `select_target.py` instead of writing the answer yourself:

- `跟踪 ID 为 99 的人`
- `切换到 ID 3`
- `继续跟踪 ID 1`

If that helper reports `found=false`, return the clarification payload exactly as a processed `init` or `track` turn.

Do not call a helper just to answer a tracking question. `reply` should usually be written by Pi directly from the persisted state and the latest frame context.

The operational scripts below are not part of one turn's reasoning path and do not live inside the skill package:

- `python scripts/run_tracking_perception.py ...`
- `python scripts/run_tracking_loop.py ...`

## Output Contract

Before returning, read [output-contracts.md](./references/output-contracts.md). It contains:

- the generic final turn payload expected by the runner
- the helper output shapes for `select_target.py` and `rewrite_memory.py`

For normal tracking turns:
1. read state files
2. decide yourself whether this is `reply`, `init`, `track`, or one clarification
3. if this is `init` or `track`, call `select_target.py`
4. if the `init` or `track` result succeeded, call `rewrite_memory.py`
5. write the final JSON yourself using the reference contract

## Output Discipline

- Prefer `tracking` over `idle` whenever the user turn is clearly about the current tracked person, the latest frame, candidate IDs, or tracking continuity.
- `idle` is only for turns that are genuinely unrelated to tracking or the current visual state.
- `session_result` must be a minimal tracking result object. Never copy `session.json`, `conversation_history`, `recent_frames`, or other raw session snapshots into it.
- Keep tracking field names canonical. Do not invent replacements such as `candidate_id`, `action_taken`, `target_confirmed`, `track_start`, `position_analysis`, or nested session-shaped payloads.
- For `processed` turns, set `tool` to `reply`, `init`, or `track`. Do not leave it `null`.
- When `reply` answers a grounded tracking question, still return `status="processed"` and `skill_name="tracking"`.
- When the user asks for an invalid ID or ambiguity remains, return a processed clarification payload, not `idle`.

## Canonical References

- [interaction-policy.md](./references/interaction-policy.md): how to reason about one turn
- [output-contracts.md](./references/output-contracts.md): canonical tool outputs
- [memory-format.md](./references/memory-format.md): canonical memory-writing rules

## Common Mistakes

- Treating the skill as a long-running process instead of a single-turn capability.
- Letting backend daemons or helper scripts become the dialogue orchestrator.
- Treating `reply`, `init`, `track`, and `rewrite_memory` as separate skills.
- Using action, pose, or temporary location as the main identity cue when stable appearance is available.
- Guessing between similar candidates instead of asking one focused clarification question.

## Notes

- The runtime persistence layer stores raw state. The agent still owns turn-by-turn reasoning.
