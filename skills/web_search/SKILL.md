---
name: "web_search"
description: "Use when the user asks for internet search, factual lookups that benefit from current web results, or short source-backed answers; run the bundled CLI (`scripts/search_web.py`) and return concise structured results."
---

# Web Search Skill

Use this skill when a turn needs current web information rather than only local state.

## Robot-Agent Contract

When this skill is used inside `robot-agent`, return exactly one raw JSON object:

```json
{
  "status": "idle" | "processed",
  "skill_name": "web_search" | null,
  "session_result": object | null,
  "latest_result_patch": object | null,
  "skill_state_patch": object | null,
  "user_preferences_patch": object | null,
  "environment_map_patch": object | null,
  "perception_cache_patch": object | null,
  "robot_response": object | null,
  "tool": "search" | null,
  "tool_output": object | null,
  "rewrite_output": object | null,
  "reason": string | null
}
```

## When To Use

- Current factual lookup
- Search the web for a named topic
- Collect a few recent links before replying

Do not use this skill for:

- Pure embodied tracking turns
- TTS generation
- Questions answerable entirely from current perception/session state

## Helper Script

- `python skills/web_search/scripts/search_web.py --query <text>`

The helper already returns structured JSON. Prefer it over ad hoc scraping logic.
