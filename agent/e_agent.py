from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
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
VISION_GROUNDING_PROMPT_PATH = PROJECT_ROOT / "agent" / "prompts" / "vision_grounding_system.md"


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start the PI TUI on the active robot-agent session and supervise continuous tracking follow-up."
    )
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--device-id", default="robot_01", help=argparse.SUPPRESS)
    parser.add_argument("--state-root", default="./.runtime/agent-runtime", help=argparse.SUPPRESS)
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--pi-bin", default="pi", help=argparse.SUPPRESS)
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
    perception_service = LocalPerceptionService(state_root=state_root)
    snapshot_path = (state_root / "perception" / "snapshot.json").resolve()
    latest_frame_artifact_path = perception_service.latest_frame_artifact_path().resolve()
    tracking_memory_path = tracking_memory_file(state_root=state_root, session_id=session_id).resolve()
    available_current_frame_path = perception_service.ensure_latest_frame_artifact()
    if available_current_frame_path is not None:
        latest_frame_note = (
            f"当前启动时已经有可用的当前画面直达文件：{str(available_current_frame_path)}。"
            "每次需要确认当前视觉时，优先直接读取这张图像，不要先读 snapshot.json 只是为了找图像路径。"
        )
    else:
        latest_frame_note = (
            f"当前启动时还没有可用的当前画面直达文件；固定路径是 {latest_frame_artifact_path}。"
            "如果这张图不存在，就明确说明当前没有可用画面。"
        )
    template = VISION_GROUNDING_PROMPT_PATH.read_text(encoding="utf-8")
    return (
        template.replace("__CURRENT_FRAME_PATH__", str(latest_frame_artifact_path))
        .replace("__CURRENT_FRAME_NOTE__", latest_frame_note)
        .replace("__SNAPSHOT_PATH__", str(snapshot_path))
        .replace("__TRACKING_MEMORY_PATH__", str(tracking_memory_path))
    )


def _pi_command(
    args: argparse.Namespace,
    *,
    state_root: Path,
    session_id: str,
    resolved_pi_args: List[str] | None = None,
) -> List[str]:
    raw_pi_args = list(resolved_pi_args if resolved_pi_args is not None else _resolved_pi_args(list(args.pi_args or [])))
    has_explicit_thinking = "--thinking" in raw_pi_args
    default_thinking_args = [] if has_explicit_thinking else ["--thinking", "minimal"]
    return [
        str(args.pi_bin),
        *default_thinking_args,
        "--no-skills",
        *_skill_args(list(args.skill or [])),
        "--append-system-prompt",
        _vision_grounding_prompt(state_root=state_root, session_id=session_id),
        *raw_pi_args,
    ]


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
    command = _sandboxed_command(
        _pi_command(
            args,
            state_root=state_root,
            session_id=session_id,
            resolved_pi_args=resolved_pi_args,
        ),
        args,
        env,
    )
    try:
        child = subprocess.Popen(command, env=env)
    except FileNotFoundError as exc:
        raise RuntimeError(f"pi executable not found: {command[0]}") from exc

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
