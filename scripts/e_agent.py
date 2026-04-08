from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path
from typing import List

from backend.cli import bootstrap_runner_session
from backend.project_paths import resolve_project_path
from backend.skills import project_skill_paths

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bootstrap the main runner session, then exec into pi with project skills loaded."
    )
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--device-id", default="robot_01")
    parser.add_argument("--state-root", default="./.runtime/agent-runtime")
    parser.add_argument("--frame-buffer-size", type=int, default=3)
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--pi-bin", default="pi")
    parser.add_argument(
        "--unsafe-no-pi-sandbox",
        action="store_true",
        help="Disable the macOS sandbox wrapper and let pi run with normal filesystem write access.",
    )
    parser.add_argument(
        "--pi-writable-dir",
        action="append",
        default=[],
        help="Extra directory that pi may write when the default project-readonly sandbox is enabled.",
    )
    parser.add_argument(
        "--skill",
        action="append",
        default=[],
        help="Optional extra skill path to append after the default project skills.",
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


def _pi_command(args: argparse.Namespace) -> List[str]:
    return [
        str(args.pi_bin),
        "--no-skills",
        *_skill_args(list(args.skill or [])),
        *_resolved_pi_args(list(args.pi_args or [])),
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
    if bool(args.unsafe_no_pi_sandbox):
        return command
    profile_path = _sandbox_profile_path(args, env)
    return ["/usr/bin/sandbox-exec", "-f", str(profile_path), *command]


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv)
    state_root = resolve_project_path(args.state_root)
    session = bootstrap_runner_session(
        state_root=state_root,
        device_id=str(args.device_id),
        session_id=args.session_id,
        frame_buffer_size=int(args.frame_buffer_size),
        fresh=bool(args.fresh),
    )
    env = dict(os.environ)
    env["ROBOT_AGENT_STATE_ROOT"] = str(state_root)
    env["ROBOT_AGENT_SESSION_ID"] = str(session.session_id)
    command = _sandboxed_command(_pi_command(args), args, env)
    try:
        os.execvpe(command[0], command, env)
        return 0
    except FileNotFoundError as exc:
        raise RuntimeError(f"pi executable not found: {command[0]}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
