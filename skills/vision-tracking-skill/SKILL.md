---
name: vision-tracking-skill
description: Use when maintaining a conversational visual tracking session over sampled video frames, especially when the user may clarify, interrupt, replace the target, or ask tracking questions during the same session.
---

# Vision Tracking Skill

## Overview

This skill runs a persistent human-in-the-loop visual tracking conversation. The host agent owns turn-by-turn decisions. The bundled Python scripts are atomic capabilities for reading state, localizing the target, rewriting tracking memory, answering grounded questions, and saving artifacts.

The core constraint is simple: keep orchestration in the agent, keep deterministic support in the scripts, and do not collapse the session into a fixed menu of user intents.

Semantic rule: `reply`, `init`, `track`, and `rewrite_memory` are tools inside this skill, not standalone skills. The files under `flows/` are tool-flow guides that explain when and how the host agent should use those tools.

## When to Use

- The user is tracking one person across sampled video frames.
- The user may interrupt, ask a question, refine the description, or replace the target mid-session.
- The latest frame already has candidate detections with stable `bounding_box_id` values.
- The host agent needs to decide whether the next move is `reply`, `init`, `track`, or `rewrite_memory`.
- The backend stores raw state, but the agent still needs to assemble working context locally.

Do not use this skill for:

- One-shot detection tasks that do not need session memory or conversational recovery.
- Identity-level face recognition workflows.
- ReID-first pipelines where appearance reasoning is only secondary.
- Backends that expect a rigid intent taxonomy or a monolithic round runner.

## MVP Boundary

- Use DashScope via the OpenAI-compatible endpoint configured in `.ENV`.
- Use the local frame queue and query plan already produced by the project runtime.
- Do not introduce identity-level face recognition in this MVP. Visible facial traits are ordinary appearance cues only.
- Treat ReID as optional weak evidence, never as the primary decision source.

## Core Pattern

For each new user turn:

1. Read the active session, current runtime batch, memory, and latest result.
2. Interpret the message in session context instead of forcing an up-front intent label.
3. Choose the smallest next move that advances the session.
4. Ask one focused clarification question when ambiguity remains.
5. Rewrite memory only after a successful `init` or `track`.

Read [interaction-policy.md](./references/interaction-policy.md) before combining tools.

## Quick Reference

| Situation | Preferred move | Primary reference |
| --- | --- | --- |
| User defines or replaces a target | `init` | [init-tool.md](./flows/init-tool.md) |
| Active target should continue on the latest batch | `track` | [track-tool.md](./flows/track-tool.md) |
| Ambiguity remains or the user says the target is wrong | focused clarification via `reply`, then rerun | [clarify-flow.md](./flows/clarify-flow.md) |
| User asks a tracking-related question | `reply` | [reply-tool.md](./flows/reply-tool.md) |
| `init` or `track` succeeds and memory should improve | `rewrite_memory` | [rewrite-memory-tool.md](./flows/rewrite-memory-tool.md) |

## Canonical References

- [interaction-policy.md](./references/interaction-policy.md): how the host agent should reason about each turn
- [output-contracts.md](./references/output-contracts.md): the only canonical tool outputs
- [memory-format.md](./references/memory-format.md): the only canonical memory-writing rules
- [prompting-guidelines.md](./references/prompting-guidelines.md): high-level prompting constraints for localization and chat

## Deterministic Helpers

- Primary runtime entrypoints: [pi_backend_bridge.py](./scripts/pi_backend_bridge.py), [pi_agent_adapter.py](./scripts/pi_agent_adapter.py), [agent_common.py](./scripts/agent_common.py)
- Integration harness helpers: [build_query_plan.py](./scripts/build_query_plan.py), [track_from_description.py](./scripts/track_from_description.py), [main_agent_locate.py](./scripts/main_agent_locate.py), [sub_agent_memory.py](./scripts/sub_agent_memory.py)

These helpers are capabilities, not a replacement for agent reasoning.

## Integration Artifacts

These files are deployment-specific adapters, not the core skill contract:

- [agent-config.json](./references/agent-config.json)
- [pi-agent-tools.json](./references/pi-agent-tools.json)
- [robot-agent-config.json](./references/robot-agent-config.json)
- [openai.yaml](./agents/openai.yaml)

## Common Mistakes

- Treating tool names as separate skills instead of capabilities inside one session skill.
- Treating the flow documents as a fixed menu of intents instead of reusable patterns.
- Letting the backend or scripts become the dialogue orchestrator.
- Using action, pose, or transient position as the main identity cue when stable appearance is available.
- Compressing memory into a neat summary instead of preserving dense, reusable appearance cues.
- Guessing between similar candidates instead of asking one focused clarification question.

## Notes

- The backend stores raw session state and accepts results. It is not the dialogue orchestrator.
- Continuous end-to-end replay is allowed only as a test harness, not as the production orchestration layer.
- All user-facing runtime entry points referenced by this skill must resolve within the skill folder itself.
