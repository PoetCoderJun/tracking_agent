---
name: describe-image
description: Use when the user asks what is visible now, wants a grounded description of the current scene, or asks about objects in the latest camera frame.
---

# Describe Image

## Overview

This is a direct vision skill.

Use the latest persisted frame as the source of truth, look at that image directly, and answer the user naturally. Do not route this through tracking, session replay, or a helper script when the task is only "what is in the picture".

## When to Use

- The user asks `画面中有什么`、`你看到了什么`、`当前画面是什么`.
- The user wants a grounded description of the latest camera frame.
- The user asks about visible objects, people, text, or layout in the current scene.

Do not use this skill for:

- target selection or tracking updates
- web lookup
- Feishu notification

## MVP Workflow

1. Read `$ROBOT_AGENT_STATE_ROOT/perception/snapshot.json` in the normal PI runtime.
2. If that env var is unavailable, fall back to `./.runtime/agent-runtime/perception/snapshot.json`.
3. Find `latest_frame.image_path`.
4. Open that image directly and inspect it with vision.
5. Answer the user in natural language.

If `snapshot.json` is missing, `latest_frame` is empty, or the image file does not exist, say that you do not currently have a usable frame and cannot describe the scene accurately.

## Rules

1. Describe only what is actually visible in the latest frame.
2. Prefer concrete visible facts over inference.
3. If text, identity, or distant details are unclear, say they are unclear.
4. Answer in the user's language.
5. Do not mention internal prompts, session state, payload formats, or file-processing details.
6. Do not call `describe_turn.py` just to answer a simple visual-description request.
7. Do not return JSON unless the user explicitly asks for JSON.

If a deterministic helper is used in this repo for integration testing or a bounded runtime flow, it should return a processed payload only; the harness/runner owns the final session-state commit.

## Response Style

- Start with the main visible subjects.
- Then mention notable background objects or text.
- Keep the answer short unless the user asks for more detail.
- If part of the image is blocked, blurred, overexposed, or cropped, say so plainly.
