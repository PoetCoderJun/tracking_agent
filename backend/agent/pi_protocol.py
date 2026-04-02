from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

from backend.config import parse_dotenv
from backend.skills import project_skill_paths


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PI_TIMEOUT_SECONDS = 90
JSON_BLOCK_PATTERN = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)
TURN_STATUSES = frozenset({"idle", "processed"})


def _message_text_parts(message: Dict[str, Any]) -> list[str]:
    parts = message.get("content", [])
    if not isinstance(parts, list):
        return []
    texts: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        if str(part.get("type", "")).strip() != "text":
            continue
        text = str(part.get("text", "")).strip()
        if text:
            texts.append(text)
    return texts


def _assistant_text(messages: list[Dict[str, Any]]) -> str:
    for message in reversed(messages):
        if str(message.get("role", "")).strip() != "assistant":
            continue
        texts = _message_text_parts(message)
        if texts:
            return "\n\n".join(texts)
    return ""


def _parse_pi_messages(stdout: str) -> list[Dict[str, Any]]:
    messages: list[Dict[str, Any]] = []
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "message_end":
            continue
        message = event.get("message")
        if isinstance(message, dict):
            messages.append(message)
    return messages


def _decoded_subprocess_output(value: str | bytes | None) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _repair_unescaped_quotes(raw: str) -> str:
    repaired: list[str] = []
    in_string = False
    escape = False
    length = len(raw)

    def next_significant(index: int) -> str:
        cursor = index + 1
        while cursor < length and raw[cursor].isspace():
            cursor += 1
        if cursor >= length:
            return ""
        return raw[cursor]

    for index, char in enumerate(raw):
        if not in_string:
            repaired.append(char)
            if char == '"':
                in_string = True
                escape = False
            continue

        if escape:
            repaired.append(char)
            escape = False
            continue

        if char == "\\":
            repaired.append(char)
            escape = True
            continue

        if char == '"':
            next_char = next_significant(index)
            if next_char in {"", ",", "}", "]", ":"}:
                repaired.append(char)
                in_string = False
            else:
                repaired.append('\\"')
            continue

        repaired.append(char)

    return "".join(repaired)


def _is_turn_payload(payload: Any) -> bool:
    return isinstance(payload, dict) and str(payload.get("status", "")).strip() in TURN_STATUSES


def _parse_json_payload(text: str) -> Optional[Dict[str, Any]]:
    stripped = text.strip()
    if not stripped:
        return None

    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        payload = None
    if _is_turn_payload(payload):
        return payload

    try:
        payload = json.loads(_repair_unescaped_quotes(stripped))
    except json.JSONDecodeError:
        payload = None
    if _is_turn_payload(payload):
        return payload

    matches = list(JSON_BLOCK_PATTERN.finditer(stripped))
    for match in reversed(matches):
        candidate = match.group(1).strip()
        if not candidate:
            continue
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            try:
                payload = json.loads(_repair_unescaped_quotes(candidate))
            except json.JSONDecodeError:
                continue
        if _is_turn_payload(payload):
            return payload

    decoder = json.JSONDecoder()
    for index, char in enumerate(stripped):
        if char != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            try:
                payload = json.loads(_repair_unescaped_quotes(stripped[index:]))
            except json.JSONDecodeError:
                continue
        if _is_turn_payload(payload):
            return payload

    return None


def _payload_from_messages(messages: list[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for message in reversed(messages):
        texts = _message_text_parts(message)
        for text in reversed(texts):
            payload = _parse_json_payload(text)
            if payload is not None:
                return payload
        if len(texts) > 1:
            payload = _parse_json_payload("\n\n".join(texts))
            if payload is not None:
                return payload
    return None


def _build_pi_prompt(*, turn_context_path: Path) -> str:
    return f"""You are running one robot-agent turn inside Pi.

Available project skills are already loaded natively into Pi for this turn. Only the `enabled_skills` listed in the turn context are installed. Choose the best matching installed skill yourself. If no installed skill applies, return an idle payload.

Read this file first:
- Turn context JSON: {turn_context_path}

The turn context file contains:
- `context_paths.route_context_path`: minimal routing context for this turn
- `state_paths.session_path`: persisted robot session state
- `service_commands.perception_read`: CLI command that reads the persisted perception snapshot
- `env_file`: environment file path for skill scripts
- `artifacts_root`: output directory for skill artifacts
- `enabled_skills`: the only skills installed for this turn

Rules:
1. Read `context_paths.route_context_path` first.
2. Use installed skills and their bundled scripts directly. Do not expect any backend skill adapter or runtime wrapper.
3. If a skill documents a deterministic entry script, call that script through bash and return its final JSON unchanged.
4. Prefer `service_commands.perception_read` before falling back to raw state files when you need the current camera/perception snapshot.
5. Only read `state_paths.session_path` if the route context and perception CLI output are insufficient and you are blocked.
6. Never edit any persisted state file yourself. The runner persists your returned payload.
7. Never write the final payload into a temp file such as `pi_output.json`. Return the raw JSON object directly in your final assistant message.
8. Do not output summaries, markdown, or explanatory prose. Return exactly one raw JSON object and nothing else.
9. If the current turn clearly falls within the scope of an installed skill, prefer that skill over `idle`.
10. `session_result` must be the minimal final turn result, never a raw session snapshot or copied `session.json`.
11. `idle` is only for turns where no installed skill applies. If a skill applies but needs clarification, or if a requested target/object is invalid or missing, return a processed clarification payload instead of `idle`.

Required output schema:
{{
  "status": "idle" | "processed",
  "skill_name": "<skill-name>" | null,
  "session_result": object | null,
  "latest_result_patch": object | null,
  "skill_state_patch": object | null,
  "user_preferences_patch": object | null,
  "environment_map_patch": object | null,
  "perception_cache_patch": object | null,
  "robot_response": object | null,
  "tool": string | null,
  "tool_output": object | null,
  "rewrite_output": object | null,
  "rewrite_memory_input": object | null,
  "reason": string | null
}}

Output rules:
- For `idle`, set `skill_name` and all patch/result fields to null, and include a short `reason`.
- For `processed`, `skill_name` and `session_result` are required.
- `session_result` is what robot-agent will persist as `latest_result`.
- `skill_state_patch` must contain only that skill's own cache fields, not an extra top-level skill-name wrapper.
- Never mutate state files directly; only return patches and results in this JSON payload.
- Never rename canonical fields defined by the chosen skill contract.
- If a helper script already returned structured fields for the final result, copy those canonical fields directly into `session_result` instead of wrapping or renaming them.
- If a deterministic skill entry script already returned the complete final payload, return that payload verbatim instead of re-composing it.
"""


def _pi_subprocess_env(env_file: Path) -> Dict[str, str]:
    subprocess_env = dict(os.environ)
    subprocess_env.update(parse_dotenv(env_file))

    if subprocess_env.get("OPENAI_API_KEY") in (None, ""):
        dashscope_api_key = subprocess_env.get("DASHSCOPE_API_KEY")
        if dashscope_api_key not in (None, ""):
            subprocess_env["OPENAI_API_KEY"] = dashscope_api_key
    if subprocess_env.get("OPENAI_BASE_URL") in (None, ""):
        dashscope_base_url = subprocess_env.get("DASHSCOPE_BASE_URL")
        if dashscope_base_url not in (None, ""):
            subprocess_env["OPENAI_BASE_URL"] = dashscope_base_url

    return subprocess_env


def _pi_command(
    *,
    pi_binary: str,
    pi_tools: str,
    enabled_skill_names: list[str],
    prompt_path: Path,
    env_file: Path,
) -> list[str]:
    command = [
        pi_binary,
        "--mode",
        "json",
        "-p",
        "--no-session",
        "--tools",
        pi_tools,
    ]

    env_values = parse_dotenv(env_file)
    if any(env_values.get(key) not in (None, "") for key in ("DASHSCOPE_API_KEY", "DASHSCOPE_BASE_URL")):
        command.extend(["--provider", "dashscope"])
        dashscope_model = env_values.get("DASHSCOPE_MAIN_MODEL") or env_values.get("DASHSCOPE_MODEL")
        if dashscope_model not in (None, ""):
            command.extend(["--model", str(dashscope_model)])

    for skill_path in project_skill_paths(enabled_skill_names):
        command.extend(["--skill", str(skill_path)])
    command.append(f"@{prompt_path}")
    return command


def _run_pi_turn(
    *,
    pi_binary: str,
    command: list[str],
    request_dir: Path,
    env_file: Path,
) -> Dict[str, Any]:
    if shutil.which(pi_binary) is None:
        raise RuntimeError(f"Pi binary not found in PATH: {pi_binary}")

    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=DEFAULT_PI_TIMEOUT_SECONDS,
            env=_pi_subprocess_env(env_file),
        )
    except subprocess.TimeoutExpired as exc:
        stdout = _decoded_subprocess_output(exc.stdout)
        stderr = _decoded_subprocess_output(exc.stderr) + f"\nTimed out after {DEFAULT_PI_TIMEOUT_SECONDS} seconds."
        request_dir.mkdir(parents=True, exist_ok=True)
        (request_dir / "pi_stdout.jsonl").write_text(stdout, encoding="utf-8")
        (request_dir / "pi_stderr.txt").write_text(stderr, encoding="utf-8")
        raise RuntimeError(
            "Pi timed out before returning a final payload.\n"
            f"stdout_path={request_dir / 'pi_stdout.jsonl'}\n"
            f"stderr_path={request_dir / 'pi_stderr.txt'}"
        )

    request_dir.mkdir(parents=True, exist_ok=True)
    (request_dir / "pi_stdout.jsonl").write_text(completed.stdout, encoding="utf-8")
    (request_dir / "pi_stderr.txt").write_text(completed.stderr, encoding="utf-8")

    messages = _parse_pi_messages(completed.stdout)
    final_text = _assistant_text(messages)
    if completed.returncode != 0:
        raise RuntimeError(
            "Pi exited with a non-zero status.\n"
            f"exit_code={completed.returncode}\n"
            f"stderr={completed.stderr.strip()}\n"
            f"assistant_output={final_text.strip()}"
        )
    payload = _payload_from_messages(messages)
    if payload is not None:
        return payload
    raise ValueError(
        "Pi did not return a valid turn payload.\n"
        f"assistant_output={final_text.strip()}\n"
        f"stdout_path={request_dir / 'pi_stdout.jsonl'}\n"
        f"stderr_path={request_dir / 'pi_stderr.txt'}"
    )
