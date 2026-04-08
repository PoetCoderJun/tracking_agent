#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from agent.pi_protocol import _resolve_pi_timeout_seconds
from agent.runner import (
    AGENT_RUNTIME_NAMESPACE,
    ENABLED_SKILLS_FIELD,
    PiAgentRunner,
    available_project_skill_names,
    normalize_enabled_skill_names,
)
from agent.session_store import AgentSessionStore
from backend.perception.stream import generate_request_id, generate_session_id
from backend.persistence import ActiveSessionStore, resolve_session_id
from backend.project_paths import resolve_project_path
from backend.tracking.deterministic import process_tracking_init_direct, process_tracking_request_direct


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one local robot-agent chat turn against persisted runtime state."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    start_parser = subparsers.add_parser(
        "start",
        help="Attach to a session and configure which skills are enabled for future chat turns.",
    )
    start_parser.add_argument(
        "--session-id",
        default=None,
        help="Optional. If omitted, reuses the current active session or creates a new one.",
    )
    start_parser.add_argument("--device-id", default="robot_01")
    start_parser.add_argument("--state-root", default="./.runtime/agent-runtime")
    start_parser.add_argument("--frame-buffer-size", type=int, default=3)

    chat_parser = subparsers.add_parser(
        "chat",
        help="Append one user chat turn, let Pi choose a skill and execute it.",
    )
    chat_parser.add_argument(
        "--session-id",
        default=None,
        help="Optional. If omitted, uses the current active session.",
    )
    chat_parser.add_argument("--text", required=True)
    chat_parser.add_argument("--device-id", default="robot_01")
    chat_parser.add_argument("--state-root", default="./.runtime/agent-runtime")
    chat_parser.add_argument("--frame-buffer-size", type=int, default=3)
    chat_parser.add_argument("--env-file", default=".ENV")
    chat_parser.add_argument("--artifacts-root", default="./.runtime/pi-agent")
    chat_parser.add_argument("--pi-binary", default="pi")
    chat_parser.add_argument("--pi-timeout-seconds", type=int, default=None)
    chat_parser.add_argument("--request-id", default=None)
    chat_parser.add_argument(
        "--skill",
        action="append",
        dest="skills",
        default=None,
        help="Optional skill override for this command. Repeat the flag or pass comma-separated names.",
    )

    repl_parser = subparsers.add_parser(
        "repl",
        help="Start an interactive local chat loop.",
    )
    repl_parser.add_argument(
        "--session-id",
        default=None,
        help="Optional. If omitted, reuses the current active session or creates a new one.",
    )
    repl_parser.add_argument("--device-id", default="robot_01")
    repl_parser.add_argument("--state-root", default="./.runtime/agent-runtime")
    repl_parser.add_argument("--frame-buffer-size", type=int, default=3)
    repl_parser.add_argument("--env-file", default=".ENV")
    repl_parser.add_argument("--artifacts-root", default="./.runtime/pi-agent")
    repl_parser.add_argument("--pi-binary", default="pi")
    repl_parser.add_argument("--pi-timeout-seconds", type=int, default=None)

    event_parser = subparsers.add_parser(
        "event",
        help="Append one event-triggered turn and let Pi choose a skill to handle it.",
    )
    event_parser.add_argument(
        "--session-id",
        default=None,
        help="Optional. If omitted, uses the current active session.",
    )
    event_parser.add_argument("--event-type", required=True)
    event_parser.add_argument("--text", default="")
    event_parser.add_argument("--device-id", default="robot_01")
    event_parser.add_argument("--state-root", default="./.runtime/agent-runtime")
    event_parser.add_argument("--frame-buffer-size", type=int, default=3)
    event_parser.add_argument("--env-file", default=".ENV")
    event_parser.add_argument("--artifacts-root", default="./.runtime/pi-agent")
    event_parser.add_argument("--pi-binary", default="pi")
    event_parser.add_argument("--pi-timeout-seconds", type=int, default=None)
    event_parser.add_argument("--request-id", default=None)
    event_parser.add_argument(
        "--skill",
        action="append",
        dest="skills",
        default=None,
        help="Optional skill override for this command. Repeat the flag or pass comma-separated names.",
    )

    tracking_track_parser = subparsers.add_parser(
        "tracking-track",
        help="Run one deterministic backend tracking step against the current session state.",
    )
    tracking_track_parser.add_argument(
        "--session-id",
        default=None,
        help="Optional. If omitted, uses the current active session.",
    )
    tracking_track_parser.add_argument("--text", default="继续跟踪")
    tracking_track_parser.add_argument("--device-id", default="robot_01")
    tracking_track_parser.add_argument("--state-root", default="./.runtime/agent-runtime")
    tracking_track_parser.add_argument("--frame-buffer-size", type=int, default=3)
    tracking_track_parser.add_argument("--env-file", default=".ENV")
    tracking_track_parser.add_argument("--artifacts-root", default="./.runtime/pi-agent")
    tracking_track_parser.add_argument("--request-id", default=None)

    tracking_init_parser = subparsers.add_parser(
        "tracking-init",
        help="Run one deterministic backend init step against the current session state.",
    )
    tracking_init_parser.add_argument(
        "--session-id",
        default=None,
        help="Optional. If omitted, uses the current active session.",
    )
    tracking_init_parser.add_argument("--text", required=True)
    tracking_init_parser.add_argument("--device-id", default="robot_01")
    tracking_init_parser.add_argument("--state-root", default="./.runtime/agent-runtime")
    tracking_init_parser.add_argument("--frame-buffer-size", type=int, default=3)
    tracking_init_parser.add_argument("--env-file", default=".ENV")
    tracking_init_parser.add_argument("--artifacts-root", default="./.runtime/pi-agent")
    tracking_init_parser.add_argument("--request-id", default=None)

    return parser.parse_args()


def _runner_from_args(args: argparse.Namespace) -> PiAgentRunner:
    enabled_skills = _validated_enabled_skills(getattr(args, "skills", None))
    timeout_seconds = args.pi_timeout_seconds
    if timeout_seconds is None:
        env_file = resolve_project_path(args.env_file)
        try:
            timeout_seconds = _resolve_pi_timeout_seconds(env_file)
        except ValueError:
            timeout_seconds = 90
    return PiAgentRunner(
        state_root=resolve_project_path(args.state_root),
        frame_buffer_size=args.frame_buffer_size,
        pi_binary=str(args.pi_binary or "pi"),
        pi_timeout_seconds=timeout_seconds,
        enabled_skills=enabled_skills,
    )


def _resolved_session_id(args: argparse.Namespace) -> str:
    session_id = resolve_session_id(
        state_root=resolve_project_path(args.state_root),
        session_id=args.session_id,
    )
    if session_id is None:
        raise ValueError("No active session found. Pass --session-id or create one first.")
    return session_id


def _session_store_from_args(args: argparse.Namespace) -> AgentSessionStore:
    return AgentSessionStore(
        state_root=resolve_project_path(args.state_root),
        frame_buffer_size=args.frame_buffer_size,
    )


def _validated_enabled_skills(raw_skill_names: object) -> list[str]:
    enabled_skills = normalize_enabled_skill_names(raw_skill_names)
    if not enabled_skills:
        return []

    available_skills = available_project_skill_names()
    unknown_skills = [name for name in enabled_skills if name not in available_skills]
    if unknown_skills:
        raise ValueError(
            f"Unknown skills requested: {', '.join(unknown_skills)}. Available skills: {', '.join(available_skills) or '(none)'}"
        )
    return enabled_skills


def _ensure_repl_session(args: argparse.Namespace) -> tuple[AgentSessionStore, str]:
    state_root = resolve_project_path(args.state_root)
    sessions = _session_store_from_args(args)
    session_id = str(args.session_id or "").strip() or resolve_session_id(
        state_root=state_root,
        session_id=None,
    )
    if not session_id:
        session_id = generate_session_id(prefix="agent")
    sessions.load(session_id=session_id, device_id=args.device_id)
    ActiveSessionStore(state_root).write(session_id)
    return sessions, session_id


def _repl_enabled_skills(
    sessions: AgentSessionStore,
    session_id: str,
    device_id: str,
) -> list[str]:
    sessions.load(session_id, device_id=device_id)
    return available_project_skill_names()


def _resolve_repl_tui_entry() -> Path:
    return resolve_project_path("./terminal/pi_agent_tui.mjs")


def _launch_repl_tui(
    *,
    args: argparse.Namespace,
    session_id: str,
    enabled_skills: list[str],
) -> int:
    tui_entry = _resolve_repl_tui_entry()
    if not tui_entry.exists():
        raise RuntimeError(f"PI TUI entrypoint not found: {tui_entry}")

    command = [
        "node",
        str(tui_entry),
        "--python",
        sys.executable,
        "--repo-root",
        str(resolve_project_path(".")),
        "--session-id",
        session_id,
        "--device-id",
        args.device_id,
        "--state-root",
        str(resolve_project_path(args.state_root)),
        "--artifacts-root",
        str(resolve_project_path(args.artifacts_root)),
        "--env-file",
        str(resolve_project_path(args.env_file)),
        "--pi-binary",
        str(args.pi_binary or "pi"),
        "--frame-buffer-size",
        str(args.frame_buffer_size),
    ]
    if args.pi_timeout_seconds is not None:
        command.extend(["--pi-timeout-seconds", str(args.pi_timeout_seconds)])
    for skill_name in available_project_skill_names():
        command.extend(["--available-skill", skill_name])
    for skill_name in enabled_skills:
        command.extend(["--enabled-skill", skill_name])

    completed = subprocess.run(
        command,
        cwd=resolve_project_path("."),
        check=False,
    )
    return int(completed.returncode)


def _run_repl(args: argparse.Namespace) -> int:
    sessions, session_id = _ensure_repl_session(args)
    enabled_skills = _repl_enabled_skills(sessions, session_id, args.device_id)
    return _launch_repl_tui(
        args=args,
        session_id=session_id,
        enabled_skills=enabled_skills,
    )


def _event_turn_text(args: argparse.Namespace) -> str:
    event_type = str(args.event_type).strip()
    event_text = str(args.text or "").strip()
    if event_text:
        return f"系统事件：{event_type}。{event_text}".strip()
    return f"系统事件：{event_type}。".strip()


def main() -> int:
    args = parse_args()
    if args.command == "start":
        state_root = resolve_project_path(args.state_root)
        sessions = _session_store_from_args(args)
        session_id = resolve_session_id(
            state_root=state_root,
            session_id=args.session_id,
        ) or generate_session_id(prefix="agent")
        session = sessions.load(session_id, device_id=args.device_id)
        available_skills = available_project_skill_names()
        enabled_skills = list(available_skills)
        sessions.patch_environment(
            session_id,
            {
                AGENT_RUNTIME_NAMESPACE: {
                    ENABLED_SKILLS_FIELD: enabled_skills,
                }
            },
        )
        ActiveSessionStore(state_root).write(session_id)
        payload = {
            "status": "started",
            "session_id": session_id,
            "device_id": session.session.get("device_id") or args.device_id,
            "enabled_skills": enabled_skills,
            "available_skills": available_skills,
        }
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    if args.command == "tracking-track":
        sessions = _session_store_from_args(args)
        session_id = _resolved_session_id(args)
        payload = process_tracking_request_direct(
            sessions=sessions,
            session_id=session_id,
            device_id=args.device_id,
            text=args.text,
            request_id=args.request_id or generate_request_id(prefix="track"),
            env_file=resolve_project_path(args.env_file),
            artifacts_root=resolve_project_path(args.artifacts_root),
        )
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    if args.command == "tracking-init":
        sessions = _session_store_from_args(args)
        session_id = _resolved_session_id(args)
        payload = process_tracking_init_direct(
            sessions=sessions,
            session_id=session_id,
            device_id=args.device_id,
            text=args.text,
            request_id=args.request_id or generate_request_id(prefix="init"),
            env_file=resolve_project_path(args.env_file),
            artifacts_root=resolve_project_path(args.artifacts_root),
        )
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    if args.command == "repl":
        return _run_repl(args)

    if args.command == "event":
        runner = _runner_from_args(args)
        session_id = _resolved_session_id(args)
        payload = runner.process_chat_request(
            session_id=session_id,
            device_id=args.device_id,
            text=_event_turn_text(args),
            request_id=args.request_id or generate_request_id(prefix="event"),
            env_file=resolve_project_path(args.env_file),
            artifacts_root=resolve_project_path(args.artifacts_root),
        )
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    if args.command != "chat":  # pragma: no cover
        raise ValueError(f"Unsupported command: {args.command}")

    runner = _runner_from_args(args)
    session_id = _resolved_session_id(args)
    payload = runner.process_chat_request(
        session_id=session_id,
        device_id=args.device_id,
        text=args.text,
        request_id=args.request_id or generate_request_id(),
        env_file=resolve_project_path(args.env_file),
        artifacts_root=resolve_project_path(args.artifacts_root),
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
