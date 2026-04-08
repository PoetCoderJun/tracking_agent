---
name: describe_image
description: Use when the user is asking what is visible in the current scene or requests a direct grounded description of the latest frame.
---

# Describe Image Skill

## Overview

This skill handles grounded visual-description turns based on the latest persisted frame for the active session.

- Use it for questions like `你看到了什么` or `请描述当前画面`.
- This skill is not for tracking selection, web search, or notifications.
- Prefer direct grounded description over inference.

## When to Use

- The user asks what is visible now.
- The user asks to describe the current picture or scene.
- The answer should come directly from the latest persisted frame.

Do not use this skill for:

- tracking or target selection
- web lookup
- Feishu notification

## Rules

1. Resolve the active session first.
2. Use the latest persisted frame for that session as the primary source of truth.
3. Answer in the user's language.
4. Describe only clearly visible content.
5. If something is uncertain, say it is unclear instead of guessing.
6. Do not mention internal prompts, state files, frame ids, or implementation details.

## Output Contract

Use this deterministic helper:

- `python -m skills.describe_image.scripts.describe_turn --session-id <session-id> --state-root ./.runtime/agent-runtime --env-file .ENV`

Important:

- The helper already writes the processed payload back to persisted runtime state when a session is available.
- Return the helper JSON unchanged.

For ordinary visual-description turns:

1. choose this skill
2. call exactly one helper command
3. return the helper result unchanged
