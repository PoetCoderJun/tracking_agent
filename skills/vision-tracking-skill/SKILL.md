---
name: vision-tracking-skill
description: Conversational visual tracking skill for maintaining a persistent human-in-the-loop tracking session over sampled video frames. Use when Codex or Claude Code should interact naturally with the user, decide how to advance the tracking session from context, and use the bundled scripts only as atomic capabilities.
---

# Vision Tracking Skill

Use this skill when the host agent needs to maintain an ongoing tracking conversation with the user, localize a described person in sampled video frames, evolve compact tracking memory, and respond naturally to interruptions, corrections, questions, or target changes without collapsing into a rigid workflow.

## What this skill owns

- A VLM-first Main Agent that outputs the current target `bbox` or `not found`
- A Sub-agent that rewrites the target memory in Markdown
- Human-in-the-loop behaviors:
  - rough initialization from a short user description
  - interruption and target replacement
  - clarification when multiple candidates remain plausible
  - tracking-related chat such as whereabouts or status questions
- A minimal local file contract for the current frame and recent history

## MVP boundary

- Use DashScope via the OpenAI-compatible endpoint configured in `.ENV`
- Use the local frame queue and query plan already produced by the project runtime
- Do not introduce face handling in this MVP
- Treat ReID as optional weak evidence only, not as the primary decision source

## Runtime entry points

- Query plan builder: `scripts/build_query_plan.py`
- One-shot replay helper: `scripts/track_from_description.py`
- Session store: `scripts/session_store.py`
- Runtime state helper: `scripts/runtime_state.py`
- Frame/query readers: `scripts/frame_manifest_reader.py`, `scripts/history_queue.py`

## Interaction model

This is one unified conversational skill, not a menu of separate user-facing modes.

For each new user turn:

1. Read the active session and current runtime context.
2. Interpret the new message in context instead of forcing an up-front closed-set intent label.
3. Decide what combination of tool calls best moves the session forward.
4. Use the flow documents below as reusable patterns, not as a rigid taxonomy.

Read [interaction-policy.md](./references/interaction-policy.md) before combining tools.

Reusable flow patterns:

1. [init.md](./flows/init.md)
2. [localize.md](./flows/localize.md)
3. [update-memory.md](./flows/update-memory.md)
4. [clarify.md](./flows/clarify.md)
5. [answer-chat.md](./flows/answer-chat.md)

## Required references

- Memory template: [memory-format.md](./references/memory-format.md)
- Output contracts: [output-contracts.md](./references/output-contracts.md)
- Prompting rules: [prompting-guidelines.md](./references/prompting-guidelines.md)
- Interaction policy: [interaction-policy.md](./references/interaction-policy.md)
- Agent prompt/config bundle: [agent-config.json](./references/agent-config.json)

## Deterministic helpers

- Frame manifest reader: [frame_manifest_reader.py](./scripts/frame_manifest_reader.py)
- Query batch helper: [history_queue.py](./scripts/history_queue.py)
- Query-plan builder wrapper: [build_query_plan.py](./scripts/build_query_plan.py)
- Given-description tracking runner: [track_from_description.py](./scripts/track_from_description.py)
- Session state helper: [session_store.py](./scripts/session_store.py)
- Runtime state helper: [runtime_state.py](./scripts/runtime_state.py)
- Main-agent locate call: [main_agent_locate.py](./scripts/main_agent_locate.py)
- Sub-agent memory call: [sub_agent_memory.py](./scripts/sub_agent_memory.py)
- Tracking chat answer call: [answer_tracking_chat.py](./scripts/answer_tracking_chat.py)
- Target crop writer: [target_crop.py](./scripts/target_crop.py)
- BBox visualization writer: [bbox_visualization.py](./scripts/bbox_visualization.py)
- Memory normalizer: [memory_rewriter.py](./scripts/memory_rewriter.py)
- Locate-result validator: [output_validator.py](./scripts/output_validator.py)
- Shared model-call helper: [agent_common.py](./scripts/agent_common.py)

## Notes

- The skill owns the full conversational tracking session.
- Python helpers must stay atomic. Do not reintroduce a monolithic round runner under `skills/` or `scaffold/`.
- Continuous end-to-end replay is allowed only as a test harness, not as the production orchestration layer.
- All user-facing runtime entry points referenced by this skill must resolve within the skill folder itself.
- Do not expose a fixed closed list of user-facing intents. Let the host agent decide how to combine the tool calls from context.
- Keep memory short, natural-language, and search-oriented.
- Rewrite memory in place instead of appending logs forever.
- Distinguish observations from hypotheses in wording.
- When multiple candidates remain plausible, ask one focused follow-up question instead of guessing.
