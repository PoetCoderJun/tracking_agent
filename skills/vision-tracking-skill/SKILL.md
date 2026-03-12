---
name: vision-tracking-skill
description: Session-based visual tracking skill for locating a user-described person in sampled video frames, maintaining compact tracking memory, handling clarification, and answering tracking-status chat. Use when Codex needs to run, inspect, or debug the tracking loop and its session artifacts in this repository.
---

# Vision Tracking Skill

Use this skill when Pi Agent needs to localize a user-specified person in the latest frame, maintain evolving tracking memory, and support clarification or tracking-related chat without breaking the session.

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

- Pi Agent core: `tracking_agent/pi_agent_core.py`
- Session store: `tracking_agent/session_store.py`
- Frame/query readers: `tracking_agent/history_queue.py`
- DashScope backend: `tracking_agent/dashscope_tracking_backend.py`

## Workflow

1. Read the current frame window from the local queue or query plan.
2. If the target is new or replaced, run [init.md](./flows/init.md).
3. Run [localize.md](./flows/localize.md) to get the current target bbox or `not found`.
4. Rewrite memory with [update-memory.md](./flows/update-memory.md).
5. If ambiguity remains, use [clarify.md](./flows/clarify.md).
6. If the user asks a tracking-related question, use [answer-chat.md](./flows/answer-chat.md).

## Required references

- Memory template: [memory-format.md](./references/memory-format.md)
- Output contracts: [output-contracts.md](./references/output-contracts.md)
- Prompting rules: [prompting-guidelines.md](./references/prompting-guidelines.md)

## Deterministic helpers

- Frame manifest reader: [frame_manifest_reader.py](./scripts/frame_manifest_reader.py)
- Query batch helper: [history_queue.py](./scripts/history_queue.py)
- Session state helper: [session_store.py](./scripts/session_store.py)
- Memory normalizer: [memory_rewriter.py](./scripts/memory_rewriter.py)
- Locate-result validator: [output_validator.py](./scripts/output_validator.py)

## Notes

- Keep memory short, natural-language, and search-oriented.
- Rewrite memory in place instead of appending logs forever.
- Distinguish observations from hypotheses in wording.
- When multiple candidates remain plausible, ask one focused follow-up question instead of guessing.
