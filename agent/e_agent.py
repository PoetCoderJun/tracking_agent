from __future__ import annotations

import argparse
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import List

from agent.project_paths import resolve_project_path
from agent.runner import run_due_tracking_step
from agent.session import AgentSessionStore, bootstrap_runner_session
from capabilities.tracking.context import TRACKING_LIFECYCLE_STOPPED
from capabilities.tracking.memory import tracking_memory_file
from skills.catalog import project_skill_paths
from world.perception.service import LocalPerceptionService

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TRACKING_POLL_SECONDS = 0.25
DEFAULT_VOICE_RATE = 16000
DEFAULT_VOICE_FRAME_MS = 32


def _default_pi_bin() -> str:
    if os.name == "nt":
        for candidate in ("pi.cmd", "pi.exe", "pi"):
            resolved = shutil.which(candidate)
            if resolved:
                return resolved
        return "pi.cmd"
    return shutil.which("pi") or "pi"


def _resolved_pi_bin(raw_pi_bin: str) -> str:
    cleaned = str(raw_pi_bin).strip()
    if not cleaned:
        return _default_pi_bin()

    if os.name == "nt":
        candidate_path = Path(cleaned)
        if candidate_path.suffix.lower() in {".cmd", ".exe", ".bat", ".ps1"}:
            return shutil.which(cleaned) or cleaned
        if candidate_path.parent != Path("."):
            return cleaned
        for candidate in (f"{cleaned}.cmd", f"{cleaned}.exe", cleaned):
            resolved = shutil.which(candidate)
            if resolved:
                return resolved
        return cleaned

    return shutil.which(cleaned) or cleaned


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start the PI TUI on the active robot-agent session and supervise continuous tracking follow-up."
    )
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--device-id", default="robot_01", help=argparse.SUPPRESS)
    parser.add_argument("--state-root", default="./.runtime/agent-runtime", help=argparse.SUPPRESS)
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--pi-bin", default=_default_pi_bin(), help=argparse.SUPPRESS)
    parser.add_argument("--voice-input", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--voice-device", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--voice-rate", type=int, default=DEFAULT_VOICE_RATE, help=argparse.SUPPRESS)
    parser.add_argument("--voice-frame-ms", type=int, default=DEFAULT_VOICE_FRAME_MS, help=argparse.SUPPRESS)
    parser.add_argument(
        "--pi-sandbox",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--unsafe-no-pi-sandbox",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--pi-writable-dir",
        action="append",
        default=[],
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--skill",
        action="append",
        default=[],
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--supervisor-poll-seconds",
        type=float,
        default=DEFAULT_TRACKING_POLL_SECONDS,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("pi_args", nargs=argparse.REMAINDER)
    return parser.parse_args(argv)


def _resolved_pi_args(raw_args: List[str]) -> List[str]:
    if raw_args and raw_args[0] == "--":
        return raw_args[1:]
    return list(raw_args)


def _skill_args(extra_skills: List[str]) -> List[str]:
    args: List[str] = []
    skill_paths = [str(path.resolve()) for path in project_skill_paths()]
    for raw in list(extra_skills or []):
        cleaned = str(raw).strip()
        if cleaned:
            skill_paths.append(str(Path(cleaned).resolve()))
    seen: set[str] = set()
    for skill_path in skill_paths:
        if skill_path in seen:
            continue
        seen.add(skill_path)
        args.extend(["--skill", skill_path])
    return args


def _vision_grounding_prompt(*, state_root: Path, session_id: str) -> str:
    snapshot_path = (state_root / "perception" / "snapshot.json").resolve()
    tracking_memory_path = tracking_memory_file(state_root=state_root, session_id=session_id).resolve()
    latest_frame = LocalPerceptionService(state_root=state_root).read_latest_frame() or {}
    latest_frame_path = str(latest_frame.get("image_path", "")).strip()
    if latest_frame_path:
        latest_frame_note = (
            f"当前启动时 latest_frame.image_path={latest_frame_path}。"
            "如果后续还要确认当前画面，必须重新读取 snapshot.json 里的 latest_frame.image_path，"
            "不要把这个启动时路径当作长期真相。"
        )
    else:
        latest_frame_note = (
            "当前启动时还没有可用的 latest_frame.image_path。"
            "需要视觉 grounding 时，先读取 snapshot.json 再决定是否有可用画面。"
        )
    return (
        "你是一个具身智能机器狗的 chat-first Agent。\n"
        "如果你想知道当前世界状态、当前画面、眼前有什么，先读取 perception snapshot，"
        f"路径是 {snapshot_path}。\n"
        "当前画面的真实来源是 snapshot.json 里的 latest_frame.image_path；"
        "读取到这个路径后，把那张图像当作你判断世界状态的依据，只回答真实可见内容，不要猜测。\n"
        f"{latest_frame_note}\n"
        "如果你想知道当前正在跟踪的人的已确认特征、正反面描述或区分点，"
        "先读取当前 session 的 tracking memory，"
        f"路径是 {tracking_memory_path}。\n"
        "如果 tracking memory 不存在或为空，就明确说明当前还没有可用的跟踪特征记忆。\n"
        "如果 snapshot.json 不存在、latest_frame 为空、或图片文件不存在，就明确说明当前没有可用画面。"
    )


def _pi_command(
    args: argparse.Namespace,
    *,
    state_root: Path,
    session_id: str,
    pi_session_dir: Path | None,
    resolved_pi_args: List[str] | None = None,
) -> List[str]:
    raw_pi_args = list(resolved_pi_args if resolved_pi_args is not None else _resolved_pi_args(list(args.pi_args or [])))
    has_explicit_thinking = "--thinking" in raw_pi_args
    default_thinking_args = [] if has_explicit_thinking else ["--thinking", "minimal"]
    has_explicit_session_dir = "--session-dir" in raw_pi_args or any(
        item.startswith("--session-dir=") for item in raw_pi_args
    )
    session_dir_args: List[str] = []
    if pi_session_dir is not None and not has_explicit_session_dir:
        session_dir_args = ["--session-dir", str(pi_session_dir)]
    return [
        _resolved_pi_bin(str(args.pi_bin)),
        *default_thinking_args,
        *session_dir_args,
        "--no-skills",
        *_skill_args(list(args.skill or [])),
        "--append-system-prompt",
        _vision_grounding_prompt(state_root=state_root, session_id=session_id),
        *raw_pi_args,
    ]


def _pi_session_dir(*, state_root: Path, session_id: str) -> Path:
    return state_root / "pi_sessions" / session_id


def _resolved_pi_session_dir(
    *,
    state_root: Path,
    session_id: str,
    resolved_pi_args: List[str],
) -> Path | None:
    raw_pi_args = list(resolved_pi_args or [])
    if "--no-session" in raw_pi_args:
        return None
    for index, item in enumerate(raw_pi_args):
        if item == "--session-dir":
            if index + 1 >= len(raw_pi_args):
                raise RuntimeError("pi args include --session-dir without a directory value.")
            cleaned = str(raw_pi_args[index + 1]).strip()
            if not cleaned:
                raise RuntimeError("pi args include --session-dir without a directory value.")
            return _real_path(cleaned)
        if item.startswith("--session-dir="):
            cleaned = item.split("=", 1)[1].strip()
            if not cleaned:
                raise RuntimeError("pi args include --session-dir without a directory value.")
            return _real_path(cleaned)

    session_dir = _pi_session_dir(state_root=state_root, session_id=session_id).resolve()
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def _escaped_sb_path(path: Path) -> str:
    return str(path).replace("\\", "\\\\").replace('"', '\\"')


def _real_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _default_pi_session_dir(env: dict[str, str]) -> Path:
    configured = str(env.get("PI_CODING_AGENT_DIR", "")).strip()
    if configured:
        return _real_path(configured)
    return _real_path(Path.home() / ".pi" / "agent")


def _sandbox_writable_dirs(args: argparse.Namespace, env: dict[str, str]) -> List[Path]:
    writable_dirs = [
        _real_path(PROJECT_ROOT / ".runtime"),
        _default_pi_session_dir(env),
        _real_path(tempfile.gettempdir()),
    ]
    for raw in list(args.pi_writable_dir or []):
        cleaned = str(raw).strip()
        if cleaned:
            writable_dirs.append(_real_path(cleaned))

    unique_dirs: List[Path] = []
    seen: set[str] = set()
    for candidate in writable_dirs:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        unique_dirs.append(candidate)
    return unique_dirs


def _sandbox_profile_text(writable_dirs: List[Path]) -> str:
    writable_rules = "\n".join(f'  (subpath "{_escaped_sb_path(path)}")' for path in writable_dirs)
    return (
        '(version 1)\n'
        '(deny default)\n'
        '(import "system.sb")\n'
        '(import "com.apple.corefoundation.sb")\n'
        '(corefoundation)\n'
        '(allow process-fork)\n'
        '(allow process-exec*)\n'
        '(allow signal)\n'
        '(allow sysctl-read)\n'
        '(allow mach-lookup)\n'
        '(allow mach-per-user-lookup)\n'
        '(allow ipc-posix-shm)\n'
        '(allow network*)\n'
        '(allow file-read*)\n'
        '(allow file-write*\n'
        f"{writable_rules}\n"
        '  (literal "/dev/tty")\n'
        '  (literal "/dev/null")\n'
        '  (literal "/dev/zero"))\n'
    )


def _sandbox_profile_path(args: argparse.Namespace, env: dict[str, str]) -> Path:
    writable_dirs = _sandbox_writable_dirs(args, env)
    runtime_root = _real_path(PROJECT_ROOT / ".runtime" / "pi-agent" / "sandbox")
    runtime_root.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        prefix="pi-readonly-",
        suffix=".sb",
        dir=runtime_root,
        delete=False,
        encoding="utf-8",
    ) as handle:
        handle.write(_sandbox_profile_text(writable_dirs))
        return Path(handle.name)


def _sandboxed_command(command: List[str], args: argparse.Namespace, env: dict[str, str]) -> List[str]:
    if bool(args.unsafe_no_pi_sandbox) or not bool(args.pi_sandbox):
        return command
    profile_path = _sandbox_profile_path(args, env)
    return ["/usr/bin/sandbox-exec", "-f", str(profile_path), *command]


def _supervisor_owner_id(session_id: str) -> str:
    return f"e-agent:{session_id}:{os.getpid()}"


def _prime_supervisor_state(*, sessions: AgentSessionStore, session_id: str, owner_id: str) -> None:
    sessions.patch_runner_state(
        session_id,
        {
            "owner_id": "",
            "supervisor_owner_id": owner_id,
            "turn_in_flight": False,
            "turn_kind": None,
            "turn_request_id": None,
            "turn_started_at": None,
        },
    )


def _cleanup_supervisor_state(
    *,
    sessions: AgentSessionStore,
    session_id: str,
    reason: str,
) -> None:
    sessions.patch_runner_state(
        session_id,
        {
            "owner_id": "",
            "supervisor_owner_id": "",
            "turn_in_flight": False,
            "turn_kind": None,
            "turn_request_id": None,
            "turn_started_at": None,
        },
    )
    tracking_state = dict((sessions.load(session_id).capabilities.get("tracking") or {}))
    if tracking_state.get("latest_target_id") not in (None, "", []):
        sessions.patch_skill_state(
            session_id,
            skill_name="tracking",
            patch={
                "lifecycle_status": TRACKING_LIFECYCLE_STOPPED,
                "stop_reason": reason,
            },
        )


def _child_env(base_env: dict[str, str], *, state_root: Path, session_id: str) -> dict[str, str]:
    env = dict(base_env)
    env["ROBOT_AGENT_STATE_ROOT"] = str(state_root)
    env["ROBOT_AGENT_SESSION_ID"] = str(session_id)
    env["ROBOT_AGENT_TURN_OWNER_ID"] = "pi"
    return env


def _voice_turn_command(
    args: argparse.Namespace,
    *,
    state_root: Path,
    session_id: str,
    pi_session_dir: Path | None,
    resolved_pi_args: List[str],
    text: str,
) -> List[str]:
    return _pi_command(
        args,
        state_root=state_root,
        session_id=session_id,
        pi_session_dir=pi_session_dir,
        resolved_pi_args=[
            *list(resolved_pi_args or []),
            "--continue",
            "-p",
            str(text).strip(),
        ],
    )


def _write_voice_text_to_console(text: str) -> None:
    from agent.windows_console_input import write_console_text

    write_console_text(text, submit=True)


class _VoiceTurnDispatcher:
    def __init__(
        self,
        *,
        args: argparse.Namespace,
        env: dict[str, str],
        state_root: Path,
        session_id: str,
        pi_session_dir: Path | None,
        resolved_pi_args: List[str],
    ) -> None:
        self._args = args
        self._env = dict(env)
        self._state_root = state_root
        self._session_id = session_id
        self._pi_session_dir = pi_session_dir
        self._resolved_pi_args = list(resolved_pi_args or [])
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="VoiceTurnDispatcher", daemon=True)
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._thread.start()

    def submit(self, text: str) -> None:
        cleaned = str(text).strip()
        if cleaned:
            self._queue.put(cleaned)

    def stop(self) -> None:
        if not self._started:
            return
        self._queue.put(None)
        self._thread.join(timeout=5.0)
        self._started = False

    def _run(self) -> None:
        while True:
            text = self._queue.get()
            if text is None:
                return
            if os.name == "nt":
                try:
                    _write_voice_text_to_console(text)
                except OSError:
                    return
                continue
            try:
                subprocess.run(
                    _sandboxed_command(
                        _voice_turn_command(
                            self._args,
                            state_root=self._state_root,
                            session_id=self._session_id,
                            pi_session_dir=self._pi_session_dir,
                            resolved_pi_args=self._resolved_pi_args,
                            text=text,
                        ),
                        self._args,
                        self._env,
                    ),
                    env=self._env,
                    stdin=subprocess.DEVNULL,
                    check=False,
                )
            except FileNotFoundError:
                return


def _create_voice_input_bridge(*, args: argparse.Namespace, on_text) -> object:
    from agent.voice_input import VoiceInputBridge

    return VoiceInputBridge(
        input_device=args.voice_device,
        rate=int(args.voice_rate),
        frame_ms=int(args.voice_frame_ms),
        on_text=on_text,
    )


def _supervise_pi(
    *,
    args: argparse.Namespace,
    sessions: AgentSessionStore,
    session_id: str,
    owner_id: str,
    env: dict[str, str],
    state_root: Path,
    resolved_pi_args: List[str],
) -> int:
    if "--no-session" in resolved_pi_args and bool(args.voice_input):
        raise RuntimeError("voice input requires pi session persistence; remove --no-session from pi args.")
    pi_session_dir = _resolved_pi_session_dir(
        state_root=state_root,
        session_id=session_id,
        resolved_pi_args=resolved_pi_args,
    )

    command = _sandboxed_command(
        _pi_command(
            args,
            state_root=state_root,
            session_id=session_id,
            pi_session_dir=pi_session_dir,
            resolved_pi_args=resolved_pi_args,
        ),
        args,
        env,
    )
    try:
        child = subprocess.Popen(command, env=env)
    except FileNotFoundError as exc:
        hint = " Try `--pi-bin pi.cmd` on Windows." if os.name == "nt" else ""
        raise RuntimeError(f"pi executable not found: {command[0]}.{hint}") from exc

    voice_dispatcher = None
    voice_bridge = None
    if bool(args.voice_input):
        voice_dispatcher = _VoiceTurnDispatcher(
            args=args,
            env=env,
            state_root=state_root,
            session_id=session_id,
            pi_session_dir=pi_session_dir,
            resolved_pi_args=resolved_pi_args,
        )
        voice_dispatcher.start()
        voice_bridge = _create_voice_input_bridge(args=args, on_text=voice_dispatcher.submit)
        voice_bridge.start()

    try:
        while True:
            return_code = child.poll()
            if return_code is not None:
                return int(return_code)
            run_due_tracking_step(
                sessions=sessions,
                session_id=session_id,
                device_id=str(args.device_id),
                env_file=resolve_project_path(".ENV"),
                artifacts_root=resolve_project_path("./.runtime/pi-agent"),
                owner_id=owner_id,
            )
            time.sleep(max(0.05, float(args.supervisor_poll_seconds)))
    finally:
        if voice_bridge is not None:
            voice_bridge.stop()
        if voice_dispatcher is not None:
            voice_dispatcher.stop()
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv)
    state_root = resolve_project_path(args.state_root)
    session = bootstrap_runner_session(
        state_root=state_root,
        device_id=str(args.device_id),
        session_id=args.session_id,
        fresh=bool(args.fresh),
    )
    sessions = AgentSessionStore(state_root=state_root)
    owner_id = _supervisor_owner_id(session.session_id)
    _prime_supervisor_state(sessions=sessions, session_id=session.session_id, owner_id=owner_id)
    resolved_pi_args = _resolved_pi_args(list(args.pi_args or []))
    env = _child_env(dict(os.environ), state_root=state_root, session_id=session.session_id)
    try:
        return _supervise_pi(
            args=args,
            sessions=sessions,
            session_id=session.session_id,
            owner_id=owner_id,
            env=env,
            state_root=state_root,
            resolved_pi_args=resolved_pi_args,
        )
    finally:
        _cleanup_supervisor_state(
            sessions=sessions,
            session_id=session.session_id,
            reason="supervisor_exit",
        )


if __name__ == "__main__":
    raise SystemExit(main())
