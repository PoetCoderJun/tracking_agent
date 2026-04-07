from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

from backend.config import parse_dotenv
from backend.skill_payload import processed_skill_payload, reply_session_result
from backend.skills import project_skill_paths


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PI_BINARY = "pi"
DEFAULT_PI_TIMEOUT_SECONDS = 90
DEFAULT_PI_TOOLS = "read,bash,grep,find,ls"
TURN_STATUSES = frozenset({"idle", "processed"})
JSON_BLOCK_PATTERN = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)
ROUTE_DECISIONS = frozenset({"direct_reply", "use_skills", "idle"})


def _first_env_value(values: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        value = str(values.get(key, "")).strip()
        if value:
            return value
    return None


def _resolve_pi_timeout_seconds(env_file: Path) -> int:
    env_values = parse_dotenv(env_file)
    raw_timeout = _first_env_value(
        env_values,
        "PI_TIMEOUT_SECONDS",
        "ROBOT_AGENT_PI_TIMEOUT_SECONDS",
    )
    if raw_timeout is None:
        return DEFAULT_PI_TIMEOUT_SECONDS
    try:
        timeout = float(raw_timeout)
    except ValueError as exc:  # pragma: no cover
        raise ValueError(f"Invalid PI timeout value: {raw_timeout}") from exc
    if timeout <= 0:
        raise ValueError(f"PI timeout must be positive: {timeout}")
    return int(timeout)


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


def _coerce_subprocess_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _is_route_payload(payload: Any) -> bool:
    return isinstance(payload, dict) and str(payload.get("decision", "")).strip() in ROUTE_DECISIONS


def _enabled_skills_from_turn_context(turn_context_path: Path) -> list[str]:
    try:
        payload = json.loads(turn_context_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw_skills = payload.get("enabled_skills") or []
    if not isinstance(raw_skills, list):
        return []
    return [str(skill).strip() for skill in raw_skills if str(skill).strip()]


def _parse_route_payload(text: str) -> Optional[dict[str, Any]]:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        payload = None
    if _is_route_payload(payload):
        return payload
    matches = list(JSON_BLOCK_PATTERN.finditer(stripped))
    for match in reversed(matches):
        candidate = match.group(1).strip()
        if not candidate:
            continue
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if _is_route_payload(payload):
            return payload
    return None


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


def _turn_image_paths(turn_context_path: Path) -> list[Path]:
    try:
        turn_context = json.loads(turn_context_path.read_text(encoding="utf-8"))
        route_path = (
            ((turn_context.get("context_paths") or {}).get("route_context_path"))
            if isinstance(turn_context, dict)
            else None
        )
        if not route_path:
            return []
        route_context = json.loads(Path(str(route_path)).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    latest_frame = route_context.get("latest_frame")
    if not isinstance(latest_frame, dict):
        return []
    image_path = str(latest_frame.get("image_path", "")).strip()
    if not image_path:
        return []
    resolved_path = Path(image_path)
    if not resolved_path.exists() or not resolved_path.is_file():
        return []
    return [resolved_path]


def _build_pi_prompt(
    *,
    turn_context_path: Path,
    enabled_skill_names: list[str] | None = None,
) -> str:
    resolved_skill_names = list(enabled_skill_names or []) or _enabled_skills_from_turn_context(turn_context_path)
    skill_list = "\n".join(f"- {name}" for name in resolved_skill_names) or "- (none)"
    route_context_text = _inline_route_context(turn_context_path)
    return f"""你是在 Pi 中执行单轮对话的机器狗 Agent。

这是一个 chat-first 的单轮执行环境。
优先根据当前用户问题、当前图片和最小 route context 直接完成这一轮。
默认使用用户上一条消息的语言回复。
如果用户说中文，默认使用简洁、自然的中文回复。
如果这一轮附带了最新帧图片文件，在回答画面描述类问题时先看图，再回答。
如果用户在问“你看到了什么”之类的问题，先直接描述图中可见内容。
除非用户明确追问，否则不要提规则、prompt、route context、skills、sensors、frame id 或内部决策过程。
不要暴露你的推理过程。
如果信息不足，就明确说不足，不要猜。

先读这个文件：
- Turn context JSON: {turn_context_path}

这个 turn context 文件包含：
- `context_paths.route_context_path`：这一轮的最小路由上下文
- `state_paths.session_path`：持久化 session 状态
- `env_file`：环境文件路径
- `artifacts_root`：产物目录
- `enabled_skills`：这一轮允许使用的 skills

规则：
1. 先读 `turn_context.json`。
2. 然后读取其中的 `context_paths.route_context_path`，在读完 route context 前不要做决定。
3. 优先使用当前帧图片和 route context；只有在信息不足且确实被卡住时，才读取 `state_paths.session_path`。
4. 如果当前输入已经足够直接回答用户，就直接回答。
5. 只有在某个 enabled skill 明显适用时，才使用该 skill。
6. 永远不要自己修改持久化状态文件；只能通过最终输出把结果交给 runner。
7. 如果这一轮需要结构化状态更新，最终输出必须是一个原始 JSON 对象，不能夹带别的内容。
8. 如果这一轮只是普通直接回复，可以直接输出自然语言。
9. `session_result` 必须是最小最终 turn 结果，绝不能拷贝整份 `session.json`。
10. 只有在既不能给 grounded 直接回复、也没有合适 skill 时，才能返回 `idle`。

要求的输出 schema：
{{
  "status": "idle" | "processed",
  "skill_name": "<skill-name>" | "agent" | null,
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

输出规则：
- 如果是 `idle`，`skill_name` 和所有 patch/result 字段都必须是 null，并提供一条简短 `reason`。
- 如果是 `processed`，`skill_name` 和 `session_result` 必填。
- 如果是不借助 project skill 的 grounded 直接回复，可以直接输出自然语言。
- 如果是直接描述画面的回复，保持简短、面向用户、只说观察结论。
- 如果你选择用结构化输出编码 grounded 直接回复，设 `skill_name` 为 `agent`，`tool` 为 `reply`，并保持 `session_result.behavior` 为 `reply`。
- `session_result` 会被 robot-agent 持久化成 `latest_result`。
- `skill_state_patch` 里只能放该 skill 自己的字段，不能再多包一层 skill 名字。
- 永远不要直接改状态文件；只能通过这个 JSON payload 返回 patches 和结果。

已启用 skills：
{skill_list}

内联 route context JSON：
{route_context_text}
"""


def _build_pi_route_prompt(
    *,
    turn_context_path: Path,
    allowed_skill_names: list[str] | None = None,
) -> str:
    _ = list(allowed_skill_names or []) or _enabled_skills_from_turn_context(turn_context_path)
    route_context_text = _inline_route_context(turn_context_path)
    return f"""你现在只负责做这一轮的最小路由决策，不执行具体 skill。

目标：
1. 判断是否可以直接回答用户。
2. 如果不能直接回答，再判断是否需要加载哪些 skills。
3. 除非某个 skill 明显必要，否则不要选择 skill。

路由原则：
- 优先直接回答。
- 如果用户是在问当前图片/当前画面里看到了什么，并且相关视觉描述 skill 已注册，可选择它。
- 只有在用户明确需要某些能力时，才选择对应 skills。
- 可以一次选择多个 skills，但只选择这一轮真正需要的最小集合。
- 不要在这一阶段输出最终用户答案之外的解释。

说明：
- 允许使用的 skills 已经作为 Pi skills 注册给你。
- 你应当依据这些已注册 skills 的描述来决定要不要选择它们。
- 不要在本 prompt 中复述或假设 skill 细节。

先读这个文件：
- Turn context JSON: {turn_context_path}

输出必须是一个 JSON 对象：
{{
  "decision": "direct_reply" | "use_skills" | "idle",
  "reply_text": string | null,
  "skill_names": string[] | null,
  "reason": string | null
}}

输出规则：
- 如果 `decision` 是 `direct_reply`，填写 `reply_text`，`skill_names` 必须为 null。
- 如果 `decision` 是 `use_skills`，填写 `skill_names`，`reply_text` 必须为 null。
- 如果 `decision` 是 `idle`，`reply_text` 和 `skill_names` 都必须为 null，并提供简短 `reason`。
- `skill_names` 中的名字必须来自已注册 skills。
- 不要输出 Markdown，不要输出额外解释，只输出 JSON。

内联 route context JSON：
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


def _payload_from_pi_stdout(stdout: str) -> Optional[dict[str, Any]]:
    messages = _parse_pi_messages(stdout)
    payload = _payload_from_messages(messages)
    if payload is not None:
        return payload
    return _parse_turn_payload(stdout)


def _route_payload_from_pi_stdout(stdout: str) -> Optional[dict[str, Any]]:
    messages = _parse_pi_messages(stdout)
    for message in reversed(messages):
        texts = _message_text_parts(message)
        for text in reversed(texts):
            payload = _parse_route_payload(text)
            if payload is not None:
                return payload
    return _parse_route_payload(stdout)


def _natural_language_reply_payload(text: str) -> Optional[dict[str, Any]]:
    cleaned = str(text).strip()
    if not cleaned:
        return None
    return processed_skill_payload(
        skill_name="agent",
        session_result=reply_session_result(cleaned),
        tool="reply",
        tool_output={"source": "assistant_text"},
    )


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
        timeout_seconds: int | None = None,
    ) -> "PiRpcClient":
        if timeout_seconds is None:
            resolved_timeout = _resolve_pi_timeout_seconds(env_file)
        else:
            resolved_timeout = int(timeout_seconds)
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
            timeout_seconds=resolved_timeout,
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
        image_paths = _turn_image_paths(turn_context_path)
        command = [*self._command, f"@{prompt_path}", *[f"@{path}" for path in image_paths]]
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
            stdout_text = _coerce_subprocess_text(exc.stdout)
            stderr_text = _coerce_subprocess_text(exc.stderr) + f"\nTimed out after {self._timeout_seconds} seconds."
            self._write_logs(request_dir=request_dir, stdout_text=stdout_text, stderr_text=stderr_text)
            payload = _payload_from_pi_stdout(stdout_text)
            if payload is not None:
                return payload
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

        payload = _payload_from_pi_stdout(completed.stdout)
        if payload is not None:
            return payload

        natural_reply_payload = _natural_language_reply_payload(final_text)
        if natural_reply_payload is not None:
            return natural_reply_payload

        raise ValueError(
            "Pi did not return a valid turn payload.\n"
            f"assistant_output={final_text.strip()}\n"
            f"stdout_path={request_dir / 'pi_stdout.jsonl'}\n"
            f"stderr_path={request_dir / 'pi_stderr.txt'}"
        )

    def run_route_prompt(
        self,
        *,
        prompt_text: str,
        turn_context_path: Path | None = None,
        request_dir: Path,
    ) -> dict[str, Any]:
        if turn_context_path is None:
            raise ValueError("turn_context_path is required for Pi turn execution")
        request_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = request_dir / "pi_route_prompt.md"
        prompt_path.write_text(prompt_text, encoding="utf-8")
        image_paths = _turn_image_paths(turn_context_path)
        command = [*self._command, f"@{prompt_path}", *[f"@{path}" for path in image_paths]]
        self._ensure_pi_available()

        completed = subprocess.run(
            command,
            cwd=self._cwd,
            env=_pi_subprocess_env(self._env_file),
            capture_output=True,
            text=True,
            timeout=self._timeout_seconds,
            check=False,
        )
        self._write_logs(
            request_dir=request_dir,
            stdout_text=completed.stdout,
            stderr_text=completed.stderr,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "Pi route stage exited with a non-zero status.\n"
                f"exit_code={completed.returncode}\n"
                f"stderr={completed.stderr.strip()}"
            )
        payload = _route_payload_from_pi_stdout(completed.stdout)
        if payload is not None:
            return payload
        raise ValueError(
            "Pi did not return a valid route payload.\n"
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
