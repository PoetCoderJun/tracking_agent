from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

from backend.config import parse_dotenv
from backend.skills import project_skill_paths


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PI_BINARY = "pi"
DEFAULT_PI_TIMEOUT_SECONDS = 90
DEFAULT_PI_TOOLS = "read,bash,grep,find,ls"
TURN_STATUSES = frozenset({"idle", "processed"})
JSON_BLOCK_PATTERN = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def _first_env_value(values: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        value = str(values.get(key, "")).strip()
        if value:
            return value
    return None


def _resolve_pi_provider_and_model(env_file: Path) -> tuple[str, str] | None:
    env_values = parse_dotenv(env_file)

    explicit_provider = _first_env_value(env_values, "PI_PROVIDER", "ROBOT_AGENT_PI_PROVIDER")
    explicit_model = _first_env_value(
        env_values,
        "PI_MODEL",
        "ROBOT_AGENT_PI_MODEL",
        "ROBOT_AGENT_MODEL",
    )
    if explicit_provider and explicit_model:
        return explicit_provider, explicit_model

    dashscope_api_key = _first_env_value(env_values, "DASHSCOPE_API_KEY")
    dashscope_model = _first_env_value(
        env_values,
        "DASHSCOPE_MAIN_MODEL",
        "DASHSCOPE_MODEL",
    )
    if dashscope_api_key and dashscope_model:
        return "dashscope", dashscope_model

    openai_api_key = _first_env_value(env_values, "OPENAI_API_KEY")
    openai_model = _first_env_value(
        env_values,
        "OPENAI_MODEL",
        "ROBOT_AGENT_MODEL",
        "PI_MODEL",
    )
    if openai_api_key and openai_model:
        return "openai", openai_model

    return None


def _is_turn_payload(payload: Any) -> bool:
    return isinstance(payload, dict) and str(payload.get("status", "")).strip() in TURN_STATUSES


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


def _parse_turn_payload(text: str) -> Optional[dict[str, Any]]:
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


def _enabled_skills_from_turn_context(turn_context_path: Path) -> list[str]:
    try:
        payload = json.loads(turn_context_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw_skills = payload.get("enabled_skills") or []
    if not isinstance(raw_skills, list):
        return []
    return [str(skill).strip() for skill in raw_skills if str(skill).strip()]


def _inline_route_context(turn_context_path: Path) -> str:
    try:
        turn_context = json.loads(turn_context_path.read_text(encoding="utf-8"))
        route_path = (
            ((turn_context.get("context_paths") or {}).get("route_context_path"))
            if isinstance(turn_context, dict)
            else None
        )
        if not route_path:
            return "(missing)"
        return Path(str(route_path)).read_text(encoding="utf-8")
    except (OSError, json.JSONDecodeError):
        return "(missing)"


def _build_pi_prompt(
    *,
    turn_context_path: Path,
    enabled_skill_names: list[str] | None = None,
) -> str:
    resolved_skill_names = list(enabled_skill_names or []) or _enabled_skills_from_turn_context(turn_context_path)
    skill_list = "\n".join(f"- {name}" for name in resolved_skill_names) or "- (none)"
    route_context_text = _inline_route_context(turn_context_path)
    return f"""You are running one robot-agent turn inside Pi.

Available project skills are already loaded natively into Pi for this turn.
Only the enabled skills for this turn may be used.
If no enabled skill applies, return an idle payload.

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
1. Read `turn_context.json` first.
2. Then read `context_paths.route_context_path` from that file before deciding anything. Do not return before reading route context.
3. Use installed skills and their bundled scripts directly. Do not invent hidden adapters or framework plumbing.
4. If a skill documents a deterministic entry script, call that script through `bash` and return its final JSON unchanged.
5. Prefer `service_commands.perception_read` before falling back to raw state files when you need the current camera/perception snapshot.
6. Only read `state_paths.session_path` if the route context and perception CLI output are insufficient and you are blocked.
7. Never edit any persisted state file yourself. The Python runner persists your returned payload.
8. Never write the final payload into a temp file such as `pi_output.json`. Return exactly one raw JSON object and nothing else.
9. `session_result` must be the minimal final turn result, never a copied `session.json`.
10. `idle` is only for turns where no enabled skill applies. If a skill applies but needs clarification, return a processed clarification payload instead of `idle`.

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

Enabled skills:
{skill_list}

Inline route context JSON:
{route_context_text}
"""


def _pi_subprocess_env(env_file: Path) -> dict[str, str]:
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


def _normalized_pi_tools(raw_tools: str) -> str:
    aliases = {
        "read": "read",
        "read_file": "read",
        "bash": "bash",
        "grep": "grep",
        "grep_search": "grep",
        "find": "find",
        "glob": "find",
        "glob_search": "find",
        "ls": "ls",
    }
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_item in str(raw_tools or DEFAULT_PI_TOOLS).split(","):
        item = raw_item.strip()
        if not item:
            continue
        canonical = aliases.get(item, aliases.get(item.lower()))
        if canonical is None or canonical in seen:
            continue
        normalized.append(canonical)
        seen.add(canonical)
    if not normalized:
        normalized = ["read", "bash", "grep", "find", "ls"]
    return ",".join(normalized)


def _pi_command(
    *,
    pi_binary: str,
    pi_tools: str,
    enabled_skill_names: list[str],
    env_file: Path,
) -> list[str]:
    resolved_provider_model = _resolve_pi_provider_and_model(env_file)
    command = [
        pi_binary,
        "--mode",
        "json",
        "-p",
        "--no-session",
    ]
    if resolved_provider_model is not None:
        provider, model = resolved_provider_model
        command.extend(["--provider", provider, "--model", model])
    command.extend(["--tools", _normalized_pi_tools(pi_tools)])
    for skill_path in project_skill_paths(enabled_skill_names):
        command.extend(["--skill", str(skill_path)])
    return command


def _message_text_parts(message: dict[str, Any]) -> list[str]:
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


def _assistant_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if str(message.get("role", "")).strip() != "assistant":
            continue
        texts = _message_text_parts(message)
        if texts:
            return "\n\n".join(texts)
    return ""


def _last_assistant_text_part(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if str(message.get("role", "")).strip() != "assistant":
            continue
        texts = _message_text_parts(message)
        if texts:
            return texts[-1]
    return ""


def _payload_from_messages(messages: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    for message in reversed(messages):
        texts = _message_text_parts(message)
        for text in reversed(texts):
            payload = _parse_turn_payload(text)
            if payload is not None:
                return payload
        if len(texts) > 1:
            payload = _parse_turn_payload("\n\n".join(texts))
            if payload is not None:
                return payload
    return None


def _payload_from_rpc_events(events: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    for event in reversed(events):
        if str(event.get("type", "")).strip() != "agent_end":
            continue
        messages = event.get("messages")
        if not isinstance(messages, list):
            continue
        filtered = [message for message in messages if isinstance(message, dict)]
        return _payload_from_messages(filtered)
    return None


def _assistant_text_from_rpc_events(events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        if str(event.get("type", "")).strip() != "agent_end":
            continue
        messages = event.get("messages")
        if not isinstance(messages, list):
            continue
        filtered = [message for message in messages if isinstance(message, dict)]
        return _assistant_text(filtered)
    return ""


def _parse_pi_messages(stdout: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
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


class PiRpcClient:
    def __init__(
        self,
        *,
        pi_binary: str,
        env_file: Path,
        command: list[str],
        cwd: Path = ROOT,
        timeout_seconds: int = DEFAULT_PI_TIMEOUT_SECONDS,
    ):
        self._pi_binary = str(pi_binary)
        self._env_file = env_file
        self._command = list(command)
        self._cwd = cwd
        self._timeout_seconds = int(timeout_seconds)

    @classmethod
    def for_skills(
        cls,
        *,
        pi_binary: str = DEFAULT_PI_BINARY,
        pi_tools: str = DEFAULT_PI_TOOLS,
        enabled_skill_names: list[str],
        env_file: Path,
        cwd: Path = ROOT,
        timeout_seconds: int = DEFAULT_PI_TIMEOUT_SECONDS,
    ) -> "PiRpcClient":
        return cls(
            pi_binary=pi_binary,
            env_file=env_file,
            command=_pi_command(
                pi_binary=pi_binary,
                pi_tools=pi_tools,
                enabled_skill_names=enabled_skill_names,
                env_file=env_file,
            ),
            cwd=cwd,
            timeout_seconds=timeout_seconds,
        )

    @property
    def command(self) -> list[str]:
        return list(self._command)

    def run_prompt(
        self,
        *,
        prompt_text: str,
        turn_context_path: Path | None = None,
        request_dir: Path,
    ) -> dict[str, Any]:
        if turn_context_path is None:
            raise ValueError("turn_context_path is required for Pi turn execution")
        request_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = request_dir / "pi_prompt.md"
        prompt_path.write_text(prompt_text, encoding="utf-8")
        command = [*self._command, f"@{prompt_path}"]
        self._ensure_pi_available()

        try:
            completed = subprocess.run(
                command,
                cwd=self._cwd,
                env=_pi_subprocess_env(self._env_file),
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout_text = str(exc.stdout or "")
            stderr_text = str(exc.stderr or "") + f"\nTimed out after {self._timeout_seconds} seconds."
            self._write_logs(request_dir=request_dir, stdout_text=stdout_text, stderr_text=stderr_text)
            raise RuntimeError(
                "Pi timed out before returning a final payload.\n"
                f"stdout_path={request_dir / 'pi_stdout.jsonl'}\n"
                f"stderr_path={request_dir / 'pi_stderr.txt'}"
            ) from exc

        self._write_logs(
            request_dir=request_dir,
            stdout_text=completed.stdout,
            stderr_text=completed.stderr,
        )

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

        direct_payload = _parse_turn_payload(completed.stdout)
        if direct_payload is not None:
            return direct_payload

        raise ValueError(
            "Pi did not return a valid turn payload.\n"
            f"assistant_output={final_text.strip()}\n"
            f"stdout_path={request_dir / 'pi_stdout.jsonl'}\n"
            f"stderr_path={request_dir / 'pi_stderr.txt'}"
        )

    def _ensure_pi_available(self) -> None:
        binary_path = Path(self._pi_binary)
        if binary_path.exists():
            return
        if shutil.which(self._pi_binary) is None:
            raise RuntimeError(f"Pi binary not found in PATH: {self._pi_binary}")

    def _write_logs(
        self,
        *,
        request_dir: Path,
        stdout_text: str,
        stderr_text: str,
    ) -> None:
        (request_dir / "pi_stdout.jsonl").write_text(stdout_text, encoding="utf-8")
        (request_dir / "pi_stderr.txt").write_text(stderr_text, encoding="utf-8")
