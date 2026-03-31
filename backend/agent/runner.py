from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from uuid import uuid4

from backend.agent.context import AgentContext
from backend.agent.context_builders import RouteContextBuilder, TrackingContextBuilder
from backend.agent.context_views import (
    TRACKING_RUNTIME_NAMESPACE,
)
from backend.agent.runtime import LocalAgentRuntime
from backend.config import parse_dotenv
from backend.perception.service import LocalPerceptionService

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PI_BINARY = "pi"
DEFAULT_PI_TOOLS = "read,bash,grep,find,ls"
DEFAULT_PI_TIMEOUT_SECONDS = 90
AGENT_RUNTIME_NAMESPACE = "agent_runtime"
ENABLED_SKILLS_FIELD = "enabled_skills"
JSON_BLOCK_PATTERN = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)
TURN_STATUSES = frozenset({"idle", "processed"})
TRACKING_SKILL_NAME = "tracking"
ROUTE_CONTEXT_BUILDER = RouteContextBuilder()
TRACKING_CONTEXT_BUILDER = TrackingContextBuilder()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _request_dir(artifacts_root: Path, session_id: str, request_id: str) -> Path:
    path = artifacts_root / "requests" / session_id / request_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def normalize_enabled_skill_names(raw_skill_names: Any) -> list[str]:
    if raw_skill_names in (None, ""):
        return []

    raw_items: list[Any]
    if isinstance(raw_skill_names, str):
        raw_items = [raw_skill_names]
    elif isinstance(raw_skill_names, Iterable):
        raw_items = list(raw_skill_names)
    else:
        raw_items = [raw_skill_names]

    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        for chunk in str(item).split(","):
            cleaned = chunk.strip()
            if not cleaned or cleaned in seen:
                continue
            normalized.append(cleaned)
            seen.add(cleaned)
    return normalized


def _available_skill_map() -> dict[str, Path]:
    skills_root = ROOT / "skills"
    if not skills_root.exists():
        return {}

    skill_map: dict[str, Path] = {}
    for candidate in sorted(skills_root.iterdir()):
        if not candidate.is_dir():
            continue
        if not (candidate / "SKILL.md").exists():
            continue
        skill_map[candidate.name] = candidate
    return skill_map


def available_project_skill_names() -> list[str]:
    return list(_available_skill_map().keys())


def _context_enabled_skills(context: AgentContext) -> list[str]:
    runtime_config = dict((context.environment_map.get(AGENT_RUNTIME_NAMESPACE) or {}))
    return normalize_enabled_skill_names(runtime_config.get(ENABLED_SKILLS_FIELD))


def _turn_context_payload(
    context: AgentContext,
    *,
    env_file: Path,
    artifacts_root: Path,
    request_id: str,
    enabled_skill_names: list[str],
    route_context_path: Path,
    tracking_context_path: Path | None,
) -> Dict[str, Any]:
    perception_query_command = [
        sys.executable,
        "-m",
        "backend.perception.cli",
        "read",
        "--state-root",
        context.state_paths["state_root"],
        "--session-id",
        context.session_id,
    ]
    payload = {
        "session_id": context.session_id,
        "request_id": request_id,
        "context_paths": {
            "route_context_path": str(route_context_path.resolve()),
        },
        "state_paths": dict(context.state_paths),
        "service_commands": {
            "perception_read": shlex.join(perception_query_command),
        },
        "env_file": str(env_file.resolve()),
        "artifacts_root": str(artifacts_root.resolve()),
        "enabled_skills": list(enabled_skill_names),
    }
    if tracking_context_path is not None:
        payload["context_paths"]["tracking_context_path"] = str(tracking_context_path.resolve())
    return payload


def _write_json(payload: Dict[str, Any], path: Path) -> Path:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    return path


def _build_pi_prompt(*, turn_context_path: Path) -> str:
    return f"""You are running one robot-agent turn inside Pi.

Available project skills are already loaded natively into Pi for this turn. Only the `enabled_skills` listed in the turn context are installed. Choose the best matching installed skill yourself. If no installed skill applies, return an idle payload.

Read this file first:
- Turn context JSON: {turn_context_path}

The turn context file contains:
- `context_paths.route_context_path`: minimal routing context for this turn
- `context_paths.tracking_context_path`: minimal tracking context for deterministic tracking scripts when the tracking skill is enabled
- `service_commands.perception_read`: CLI command that reads the persisted perception snapshot
- `env_file`: environment file path for skill scripts
- `artifacts_root`: output directory for skill artifacts
- `enabled_skills`: the only skills installed for this turn

Rules:
1. Read `context_paths.route_context_path` first.
2. If you route into tracking, read `context_paths.tracking_context_path` and prefer that specialized context over raw persisted state.
3. Use installed skills and their bundled scripts directly. Do not expect any backend skill adapter or runtime wrapper.
4. If a skill needs deterministic help, call its scripts through bash.
5. If the specialized context files are insufficient, prefer `service_commands.perception_read` before falling back to raw state files.
6. Only read `state_paths.session_path` or `state_paths.agent_memory_path` if the specialized context files and perception CLI output are insufficient and you are blocked.
7. Never edit any persisted state file yourself. The runner persists your returned payload.
8. Never write the final payload into a temp file such as `pi_output.json`. Return the raw JSON object directly in your final assistant message.
9. Do not output summaries, markdown, or explanatory prose. Return exactly one raw JSON object and nothing else.
10. If the current turn clearly falls within the scope of an installed skill, prefer that skill over `idle`.
11. `session_result` must be the minimal final turn result, never a raw session snapshot or copied `session.json`.
12. `idle` is only for turns where no installed skill applies. If a skill applies but needs clarification, or if a requested target/object is invalid or missing, return a processed clarification payload instead of `idle`.

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


def _project_skill_paths(enabled_skills: Any = None) -> list[Path]:
    skill_map = _available_skill_map()
    requested = normalize_enabled_skill_names(enabled_skills)
    if not requested:
        return list(skill_map.values())

    missing = [name for name in requested if name not in skill_map]
    if missing:
        available = ", ".join(skill_map.keys()) or "(none)"
        raise ValueError(
            f"Unknown skills requested: {', '.join(missing)}. Available skills: {available}"
        )
    return [skill_map[name] for name in requested]


def _pi_subprocess_env(env_file: Path) -> Dict[str, str]:
    subprocess_env = dict(os.environ)
    subprocess_env.update(parse_dotenv(env_file))

    # DashScope exposes an OpenAI-compatible endpoint, so mirror its auth vars for Pi.
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

    for skill_path in _project_skill_paths(enabled_skill_names):
        command.extend(["--skill", str(skill_path)])
    command.append(f"@{prompt_path}")
    return command


def _run_pi_turn(
    *,
    pi_binary: str,
    context: AgentContext,
    env_file: Path,
    artifacts_root: Path,
    request_id: str,
    pi_tools: str,
    enabled_skill_names: list[str],
) -> Dict[str, Any]:
    if shutil.which(pi_binary) is None:
        raise RuntimeError(f"Pi binary not found in PATH: {pi_binary}")

    request_dir = _request_dir(artifacts_root, context.session_id, request_id)
    route_context_path = _write_json(
        ROUTE_CONTEXT_BUILDER.build(
            context,
            request_id=request_id,
            enabled_skill_names=enabled_skill_names,
        ),
        request_dir / "route_context.json",
    )
    tracking_context_path = None
    if TRACKING_SKILL_NAME in enabled_skill_names:
        tracking_context_path = _write_json(
            TRACKING_CONTEXT_BUILDER.build(context, request_id=request_id),
            request_dir / "tracking_context.json",
        )
    turn_context_path = _write_json(
        _turn_context_payload(
            context,
            env_file=env_file,
            artifacts_root=artifacts_root,
            request_id=request_id,
            enabled_skill_names=enabled_skill_names,
            route_context_path=route_context_path,
            tracking_context_path=tracking_context_path,
        ),
        request_dir / "turn_context.json",
    )
    prompt_path = request_dir / "pi_prompt.md"
    prompt_path.write_text(_build_pi_prompt(turn_context_path=turn_context_path), encoding="utf-8")

    command = _pi_command(
        pi_binary=pi_binary,
        pi_tools=pi_tools,
        enabled_skill_names=enabled_skill_names,
        prompt_path=prompt_path,
        env_file=env_file,
    )

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
        (request_dir / "pi_stdout.jsonl").write_text(stdout, encoding="utf-8")
        (request_dir / "pi_stderr.txt").write_text(stderr, encoding="utf-8")
        raise RuntimeError(
            "Pi timed out before returning a final payload.\n"
            f"stdout_path={request_dir / 'pi_stdout.jsonl'}\n"
            f"stderr_path={request_dir / 'pi_stderr.txt'}"
        )

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


def _as_optional_dict(value: Any, field_name: str) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object or null")
    return dict(value)


def _rewrite_memory_paths(request: Dict[str, Any]) -> tuple[Optional[str], list[str]]:
    crop_path = None if request.get("crop_path") in (None, "") else str(request["crop_path"]).strip()
    frame_paths = [
        str(path).strip()
        for path in list(request.get("frame_paths") or [])
        if str(path).strip()
    ]
    return crop_path, frame_paths


def _tracking_rewrite_job_dir(runtime: LocalAgentRuntime, *, session_id: str, job_id: str) -> Path:
    context = runtime.context(session_id)
    return Path(str(context.state_paths["session_dir"])) / "tracking_rewrite_jobs" / job_id


def _write_tracking_rewrite_json(path: Path, payload: Dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    return path


def _tracking_rewrite_status_payload(
    *,
    job_id: str,
    session_id: str,
    status: str,
    task: str,
    frame_id: str,
    target_id: int,
    crop_path: str,
    frame_paths: list[str],
    requested_at: Optional[str] = None,
    updated_at: Optional[str] = None,
    started_at: Optional[str] = None,
    completed_at: Optional[str] = None,
    exit_code: Optional[int] = None,
    reason: Optional[str] = None,
    error: Optional[str] = None,
    result_path: Optional[str] = None,
    stdout_path: Optional[str] = None,
    stderr_path: Optional[str] = None,
    pid: Optional[int] = None,
) -> Dict[str, Any]:
    return {
        "job_id": job_id,
        "session_id": session_id,
        "status": status,
        "task": task,
        "frame_id": frame_id,
        "target_id": int(target_id),
        "crop_path": crop_path,
        "frame_paths": list(frame_paths),
        "requested_at": requested_at,
        "started_at": started_at,
        "completed_at": completed_at,
        "updated_at": updated_at or _utc_now(),
        "exit_code": exit_code,
        "reason": reason,
        "error": error,
        "result_path": result_path,
        "stdout_path": stdout_path,
        "stderr_path": stderr_path,
        "pid": pid,
    }


def _tracking_rewrite_job_is_latest(
    runtime: LocalAgentRuntime,
    *,
    session_id: str,
    job_id: str,
) -> bool:
    context = runtime.context(session_id)
    runtime_state = dict(context.skill_cache.get(TRACKING_RUNTIME_NAMESPACE) or {})
    if str(runtime_state.get("latest_rewrite_job_id", "")).strip() == job_id:
        return True
    tracking_state = dict(context.skill_cache.get(TRACKING_SKILL_NAME) or {})
    return str(tracking_state.get("latest_rewrite_job_id", "")).strip() == job_id


def _update_latest_tracking_rewrite_state(
    runtime: LocalAgentRuntime,
    *,
    session_id: str,
    job_id: str,
    status: str,
    task: str,
    log_dir: Path,
    status_path: Path,
    requested_at: Optional[str] = None,
    completed_at: Optional[str] = None,
    reason: Optional[str] = None,
    error: Optional[str] = None,
    result_path: Optional[Path] = None,
) -> None:
    if not _tracking_rewrite_job_is_latest(runtime, session_id=session_id, job_id=job_id):
        return
    patch: Dict[str, Any] = {
        "latest_rewrite_job_id": job_id,
        "latest_rewrite_status": status,
        "latest_rewrite_task": task,
        "latest_rewrite_log_dir": str(log_dir),
        "latest_rewrite_status_path": str(status_path),
        "latest_rewrite_requested_at": requested_at,
    }
    if completed_at is not None:
        patch["latest_rewrite_completed_at"] = completed_at
    if reason is not None:
        patch["latest_rewrite_reason"] = reason
    if error is not None:
        patch["latest_rewrite_error"] = error
    else:
        patch["latest_rewrite_error"] = None
    if result_path is not None:
        patch["latest_rewrite_result_path"] = str(result_path)
    runtime.update_skill_cache(
        session_id,
        skill_name=TRACKING_RUNTIME_NAMESPACE,
        payload=patch,
    )


def _apply_tracking_rewrite_output(
    *,
    runtime: LocalAgentRuntime,
    session_id: str,
    rewrite_output: Dict[str, Any],
) -> None:
    runtime.update_skill_cache(
        session_id,
        skill_name=TRACKING_SKILL_NAME,
        payload={"latest_memory": rewrite_output["memory"]},
    )


def _schedule_tracking_memory_rewrite(
    *,
    runtime: LocalAgentRuntime,
    session_id: str,
    rewrite_memory_input: Dict[str, Any],
    env_file: Path,
) -> None:
    crop_path, frame_paths = _rewrite_memory_paths(rewrite_memory_input)
    if crop_path in (None, "") or not frame_paths:
        return

    context = runtime.context(session_id)
    job_id = f"rewrite_{uuid4().hex}"
    job_dir = _tracking_rewrite_job_dir(runtime, session_id=session_id, job_id=job_id)
    status_path = job_dir / "status.json"
    stdout_path = job_dir / "stdout.log"
    stderr_path = job_dir / "stderr.log"
    requested_at = _utc_now()
    _write_tracking_rewrite_json(
        status_path,
        _tracking_rewrite_status_payload(
            job_id=job_id,
            session_id=session_id,
            status="queued",
            task=str(rewrite_memory_input["task"]),
            frame_id=str(rewrite_memory_input["frame_id"]),
            target_id=int(rewrite_memory_input["target_id"]),
            crop_path=crop_path,
            frame_paths=frame_paths,
            requested_at=requested_at,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
        ),
    )
    runtime.update_skill_cache(
        session_id,
        skill_name=TRACKING_RUNTIME_NAMESPACE,
        payload={
            "latest_rewrite_job_id": job_id,
            "latest_rewrite_status": "queued",
            "latest_rewrite_task": str(rewrite_memory_input["task"]),
            "latest_rewrite_log_dir": str(job_dir),
            "latest_rewrite_status_path": str(status_path),
            "latest_rewrite_requested_at": requested_at,
            "latest_rewrite_error": None,
        },
    )
    _update_latest_tracking_rewrite_state(
        runtime,
        session_id=session_id,
        job_id=job_id,
        status="queued",
        task=str(rewrite_memory_input["task"]),
        log_dir=job_dir,
        status_path=status_path,
        requested_at=requested_at,
    )
    command = [
        sys.executable,
        "skills/tracking/scripts/run_tracking_rewrite_worker.py",
        "--state-root",
        str(context.state_paths["state_root"]),
        "--job-id",
        job_id,
        "--job-dir",
        str(job_dir),
        "--session-id",
        session_id,
        "--memory-file",
        str(context.state_paths["agent_memory_path"]),
        "--task",
        str(rewrite_memory_input["task"]),
        "--crop-path",
        crop_path,
        "--frame-id",
        str(rewrite_memory_input["frame_id"]),
        "--target-id",
        str(rewrite_memory_input["target_id"]),
        "--env-file",
        str(env_file),
    ]
    for frame_path in frame_paths:
        command.extend(["--frame-path", frame_path])

    stdout_handle = stdout_path.open("a", encoding="utf-8")
    stderr_handle = stderr_path.open("a", encoding="utf-8")
    try:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=stdout_handle,
            stderr=stderr_handle,
            text=True,
            start_new_session=True,
        )
    except Exception as exc:
        stdout_handle.close()
        stderr_handle.close()
        completed_at = _utc_now()
        _write_tracking_rewrite_json(
            status_path,
            _tracking_rewrite_status_payload(
                job_id=job_id,
                session_id=session_id,
                status="failed",
                task=str(rewrite_memory_input["task"]),
                frame_id=str(rewrite_memory_input["frame_id"]),
                target_id=int(rewrite_memory_input["target_id"]),
                crop_path=crop_path,
                frame_paths=frame_paths,
                requested_at=requested_at,
                completed_at=completed_at,
                exit_code=1,
                error=str(exc),
                stdout_path=str(stdout_path),
                stderr_path=str(stderr_path),
            ),
        )
        _update_latest_tracking_rewrite_state(
            runtime,
            session_id=session_id,
            job_id=job_id,
            status="failed",
            task=str(rewrite_memory_input["task"]),
            log_dir=job_dir,
            status_path=status_path,
            requested_at=requested_at,
            completed_at=completed_at,
            error=str(exc),
        )
        return
    finally:
        stdout_handle.close()
        stderr_handle.close()

    _write_tracking_rewrite_json(
        status_path,
        _tracking_rewrite_status_payload(
            job_id=job_id,
            session_id=session_id,
            status="queued",
            task=str(rewrite_memory_input["task"]),
            frame_id=str(rewrite_memory_input["frame_id"]),
            target_id=int(rewrite_memory_input["target_id"]),
            crop_path=crop_path,
            frame_paths=frame_paths,
            requested_at=requested_at,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            pid=process.pid,
        ),
    )


def _normalize_skill_state_patch(skill_name: str, patch: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if patch is None:
        return None
    nested = patch.get(skill_name)
    if len(patch) == 1 and isinstance(nested, dict):
        return dict(nested)
    return patch


class PiAgentRunner:
    def __init__(
        self,
        *,
        state_root: Path,
        frame_buffer_size: int = 3,
        pi_binary: str = DEFAULT_PI_BINARY,
        pi_tools: str = DEFAULT_PI_TOOLS,
        enabled_skills: Any = None,
    ):
        self._runtime = LocalAgentRuntime(
            state_root=state_root,
            frame_buffer_size=frame_buffer_size,
        )
        self._pi_binary = pi_binary
        self._pi_tools = pi_tools
        self._enabled_skills = normalize_enabled_skill_names(enabled_skills)

    @property
    def runtime(self) -> LocalAgentRuntime:
        return self._runtime

    def process_chat_request(
        self,
        *,
        session_id: str,
        device_id: str,
        text: str,
        request_id: str,
        env_file: Path,
        artifacts_root: Path,
    ) -> Dict[str, Any]:
        self._runtime.append_chat_request(
            session_id=session_id,
            device_id=device_id,
            text=text,
            request_id=request_id,
        )
        context = self._runtime.context(session_id, device_id=device_id)
        enabled_skill_names = (
            list(self._enabled_skills)
            if self._enabled_skills
            else _context_enabled_skills(context) or available_project_skill_names()
        )
        if enabled_skill_names == [TRACKING_SKILL_NAME]:
            tracking_state = dict((context.skill_cache.get(TRACKING_SKILL_NAME) or {}))
            if tracking_state.get("latest_target_id") in (None, "", []):
                return self.process_tracking_init_direct(
                    session_id=session_id,
                    device_id=device_id,
                    text=text,
                    request_id=request_id,
                    env_file=env_file,
                    artifacts_root=artifacts_root,
                )
        return self.process_session(
            session_id=session_id,
            request_id=request_id,
            env_file=env_file,
            artifacts_root=artifacts_root,
        )

    def _tracking_wait_payload(
        self,
        *,
        session_id: str,
        device_id: str,
        reason: str,
    ) -> Dict[str, Any]:
        context = self._runtime.context(session_id, device_id=device_id)
        latest_observation = LocalPerceptionService(self._runtime.state_root).latest_camera_observation(
            session_id=session_id,
        )
        latest_frame_id = None
        if latest_observation is not None:
            latest_frame_id = (latest_observation.get("payload") or {}).get("frame_id")
        tracking_state = dict((context.skill_cache.get("tracking") or {}))
        target_id = tracking_state.get("latest_target_id")
        text = "当前不确定，保持等待。"
        return {
            "status": "processed",
            "skill_name": "tracking",
            "session_result": {
                "behavior": "track",
                "frame_id": latest_frame_id,
                "target_id": target_id,
                "bounding_box_id": target_id,
                "found": False,
                "decision": "wait",
                "text": text,
                "reason": reason,
            },
            "latest_result_patch": None,
            "skill_state_patch": {
                "pending_question": None,
            },
            "user_preferences_patch": None,
            "environment_map_patch": None,
            "perception_cache_patch": None,
            "robot_response": {
                "action": "wait",
                "text": text,
            },
            "tool": "track",
            "tool_output": {
                "behavior": "track",
                "decision": "wait",
                "text": text,
                "reason": reason,
            },
            "rewrite_output": None,
            "rewrite_memory_input": None,
            "reason": reason,
        }

    def process_tracking_request_direct(
        self,
        *,
        session_id: str,
        device_id: str,
        text: str,
        request_id: str,
        env_file: Path,
        artifacts_root: Path,
        recovery_mode: bool = False,
        missing_target_id: int | None = None,
        candidate_track_id_floor_exclusive: int | None = None,
    ) -> Dict[str, Any]:
        self._runtime.append_chat_request(
            session_id=session_id,
            device_id=device_id,
            text=text,
            request_id=request_id,
        )
        context = self._runtime.context(session_id, device_id=device_id)
        request_dir = _request_dir(artifacts_root, session_id, request_id)
        tracking_context_path = _write_json(
            TRACKING_CONTEXT_BUILDER.build(
                context,
                request_id=request_id,
                recovery_mode=recovery_mode,
                missing_target_id=missing_target_id,
                candidate_track_id_floor_exclusive=candidate_track_id_floor_exclusive,
            ),
            request_dir / "tracking_context.json",
        )
        command = [
            sys.executable,
            "skills/tracking/scripts/run_tracking_track.py",
            "--tracking-context-file",
            str(tracking_context_path),
            "--user-text",
            str(text),
            "--env-file",
            str(env_file),
            "--artifacts-root",
            str(artifacts_root),
        ]
        completed = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            return self._apply_processed_payload(
                session_id=session_id,
                pi_payload=self._tracking_wait_payload(
                    session_id=session_id,
                    device_id=device_id,
                    reason=(
                        "Direct tracking turn failed.\n"
                        f"exit_code={completed.returncode}\n"
                        f"stderr={completed.stderr.strip()}\n"
                        f"stdout={completed.stdout.strip()}"
                    ),
                ),
                env_file=env_file,
            )
        payload = _parse_json_payload(completed.stdout)
        if payload is None:
            return self._apply_processed_payload(
                session_id=session_id,
                pi_payload=self._tracking_wait_payload(
                    session_id=session_id,
                    device_id=device_id,
                    reason=(
                        "Direct tracking turn did not return a valid turn payload.\n"
                        f"stdout={completed.stdout.strip()}"
                    ),
                ),
                env_file=env_file,
            )
        return self._apply_processed_payload(
            session_id=session_id,
            pi_payload=payload,
            env_file=env_file,
        )

    def process_tracking_init_direct(
        self,
        *,
        session_id: str,
        device_id: str,
        text: str,
        request_id: str,
        env_file: Path,
        artifacts_root: Path,
    ) -> Dict[str, Any]:
        context = self._runtime.context(session_id, device_id=device_id)
        request_dir = _request_dir(artifacts_root, session_id, request_id)
        tracking_context_path = _write_json(
            TRACKING_CONTEXT_BUILDER.build(context, request_id=request_id),
            request_dir / "tracking_context.json",
        )
        command = [
            sys.executable,
            "skills/tracking/scripts/run_tracking_init.py",
            "--tracking-context-file",
            str(tracking_context_path),
            "--target-description",
            str(text),
            "--env-file",
            str(env_file),
            "--artifacts-root",
            str(artifacts_root),
        ]
        completed = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "Direct tracking init failed.\n"
                f"exit_code={completed.returncode}\n"
                f"stderr={completed.stderr.strip()}\n"
                f"stdout={completed.stdout.strip()}"
            )
        payload = _parse_json_payload(completed.stdout)
        if payload is None:
            raise ValueError(
                "Direct tracking init did not return a valid turn payload.\n"
                f"stdout={completed.stdout.strip()}"
            )
        return self._apply_processed_payload(
            session_id=session_id,
            pi_payload=payload,
            env_file=env_file,
        )

    def process_session(
        self,
        *,
        session_id: str,
        request_id: str,
        env_file: Path,
        artifacts_root: Path,
    ) -> Dict[str, Any]:
        context = self._runtime.context(session_id)
        enabled_skill_names = (
            list(self._enabled_skills)
            if self._enabled_skills
            else _context_enabled_skills(context) or available_project_skill_names()
        )
        last_error: Exception | None = None
        pi_payload: Dict[str, Any] | None = None
        for _ in range(3):
            try:
                pi_payload = _run_pi_turn(
                    pi_binary=self._pi_binary,
                    context=context,
                    env_file=env_file,
                    artifacts_root=artifacts_root,
                    request_id=request_id,
                    pi_tools=self._pi_tools,
                    enabled_skill_names=enabled_skill_names,
                )
                break
            except (RuntimeError, ValueError) as exc:
                message = str(exc)
                retryable = (
                    "valid turn payload" in message
                    or "timed out" in message.lower()
                )
                if not retryable:
                    raise
                last_error = exc
        if pi_payload is None:
            assert last_error is not None
            raise last_error

        status = str(pi_payload.get("status", "")).strip()
        if status == "idle":
            latest_observation = LocalPerceptionService(self._runtime.state_root).latest_camera_observation(
                session_id=context.session_id,
            )
            return {
                "session_id": context.session_id,
                "skill_name": None if pi_payload.get("skill_name") in (None, "") else str(pi_payload.get("skill_name")),
                "status": "idle",
                "frame_id": None
                if latest_observation is None
                else (latest_observation.get("payload") or {}).get("frame_id"),
                "reason": str(pi_payload.get("reason", "")).strip() or "No skill accepted the current turn.",
                "raw_session": context.raw_session,
            }
        return self._apply_processed_payload(
            session_id=session_id,
            pi_payload=pi_payload,
            env_file=env_file,
        )

    def _apply_processed_payload(
        self,
        *,
        session_id: str,
        pi_payload: Dict[str, Any],
        env_file: Path,
    ) -> Dict[str, Any]:
        skill_name = str(pi_payload.get("skill_name", "")).strip()
        if not skill_name:
            raise ValueError("Processed Pi payload is missing skill_name")
        tool_output = _as_optional_dict(pi_payload.get("tool_output"), "tool_output")
        rewrite_output = _as_optional_dict(pi_payload.get("rewrite_output"), "rewrite_output")
        rewrite_memory_input = _as_optional_dict(
            pi_payload.get("rewrite_memory_input"),
            "rewrite_memory_input",
        )
        session_result = _as_optional_dict(pi_payload.get("session_result"), "session_result")
        if session_result is None:
            raise ValueError("Processed Pi payload is missing session_result")

        current_context = self._runtime.apply_skill_result(session_id, session_result)
        latest_result_patch = _as_optional_dict(
            pi_payload.get("latest_result_patch"),
            "latest_result_patch",
        )
        if latest_result_patch:
            current_context = self._runtime.patch_latest_result(
                session_id=session_id,
                patch=latest_result_patch,
                expected_request_id=session_result.get("request_id"),
                expected_frame_id=session_result.get("frame_id"),
            )

        user_preferences_patch = _as_optional_dict(
            pi_payload.get("user_preferences_patch"),
            "user_preferences_patch",
        )
        if user_preferences_patch:
            current_context = self._runtime.update_user_preferences(session_id, user_preferences_patch)

        environment_map_patch = _as_optional_dict(
            pi_payload.get("environment_map_patch"),
            "environment_map_patch",
        )
        if environment_map_patch:
            current_context = self._runtime.update_environment_map(session_id, environment_map_patch)

        perception_cache_patch = _as_optional_dict(
            pi_payload.get("perception_cache_patch"),
            "perception_cache_patch",
        )
        if perception_cache_patch:
            current_context = self._runtime.update_perception_cache(session_id, perception_cache_patch)

        skill_state_patch = _as_optional_dict(
            pi_payload.get("skill_state_patch"),
            "skill_state_patch",
        )
        skill_state_patch = _normalize_skill_state_patch(skill_name, skill_state_patch)
        if skill_state_patch:
            current_context = self._runtime.update_skill_cache(
                session_id,
                skill_name=skill_name,
                payload=skill_state_patch,
            )

        if skill_name == TRACKING_SKILL_NAME and rewrite_memory_input:
            _schedule_tracking_memory_rewrite(
                runtime=self._runtime,
                session_id=session_id,
                rewrite_memory_input=rewrite_memory_input,
                env_file=env_file,
            )

        final_context = self._runtime.context(session_id)
        return {
            "session_id": session_id,
            "status": "processed",
            "skill_name": skill_name,
            "session_result": session_result,
            "latest_result_patch": latest_result_patch,
            "skill_state_patch": skill_state_patch,
            "user_preferences_patch": user_preferences_patch,
            "environment_map_patch": environment_map_patch,
            "perception_cache_patch": perception_cache_patch,
            "robot_response": pi_payload.get("robot_response") or session_result.get("robot_response"),
            "tool": pi_payload.get("tool"),
            "tool_output": tool_output,
            "rewrite_output": rewrite_output,
            "rewrite_memory_input": rewrite_memory_input,
            "latest_result": final_context.raw_session.get("latest_result"),
            "raw_session": final_context.raw_session,
        }
