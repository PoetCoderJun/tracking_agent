---
name: tts
description: Use when the robot should say or speak one short message aloud as a normal capability turn.
---

# TTS Skill

## Overview

This skill turns one text instruction into one speech/tts action.

- Use it when the user explicitly asks the robot to say, speak, or播报 something.
- This is a single-call capability, not a long-running audio service.
- The helper records the side effect and returns machine-readable details for the turn.

## When to Use

- The user says `说一句...` / `播报...` / `念一下...`.
- The turn is about one speech action, not tracking or web lookup.
- The robot should vocalize a short message to the local environment.

Do not use this skill for:

- tracking turns
- notification turns aimed at Feishu
- open-ended chat where no explicit speak action is requested

## Rules

1. Resolve the active session first.
2. In this runtime, prefer `ROBOT_AGENT_SESSION_ID` and `ROBOT_AGENT_STATE_ROOT` from the environment over hardcoded runtime paths.
3. Decide whether this turn is asking for one speech/tts action.
4. If yes, call the helper once.
5. After the helper completes, reply naturally to the user with the speak result.

## Helper Script

Use this deterministic helper:

- `python -m skills.tts.scripts.speak_turn --session-id <session-id> --state-root ./.runtime/agent-runtime --artifacts-root ./.runtime/pi-agent --env-file .ENV --text ...`
- In the normal PI runtime, prefer:
  `python -m skills.tts.scripts.speak_turn --session-id "$ROBOT_AGENT_SESSION_ID" --state-root "$ROBOT_AGENT_STATE_ROOT" --artifacts-root ./.runtime/pi-agent --env-file .ENV --text "..."`

Important:

- The helper is only a thin entrypoint; backend turn logic assembles and applies the processed payload.
- If `ROBOT_TTS_COMMAND` is configured, the helper will execute it once with the text appended as the final argument.
- Without `ROBOT_TTS_COMMAND`, the helper still records a mock tts outbox entry so the capability remains testable.
- Do not expose helper JSON to the user.

## Output Contract

For handled turns:

1. choose this skill
2. call exactly one helper command
3. answer the user naturally after the helper completes
