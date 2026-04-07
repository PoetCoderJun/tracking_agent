---
name: describe_image
description: Use when the user is asking what is visible in the current image or asks for a direct description of the current scene.
---

# Describe Image Skill

## Overview

This skill handles grounded visual-description turns based on the current image only.

- Use it for questions like “你看到了什么”, “请描述当前画面”, or “请详细描述现在你看到的画面”.
- This skill is not for tracking selection, web search, or notifications.
- Prefer direct, grounded description over inference.

## When to Use

- The user asks what is visible now.
- The user asks to describe the current picture or scene.
- The answer should come directly from the attached current frame image.

Do not use this skill for:

- tracking or target selection
- web lookup
- Feishu notification

## Rules

1. Read `turn_context.json` first.
2. Read `context_paths.route_context_path`.
3. Use the attached latest-frame image as the primary source of truth.
4. Answer in the user's language.
5. Describe only clearly visible content.
6. If something is uncertain, say it is unclear instead of guessing.
7. Do not mention internal rules, prompts, route context, skills, sensors, or frame ids.

## Output Contract

Use this deterministic helper:

- `python -m skills.describe_image.scripts.describe_turn --turn-context-file <turn_context.json>`

For ordinary visual-description turns:

1. choose this skill
2. call exactly one helper command
3. return the helper result unchanged
