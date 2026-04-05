#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DEMO_VIDEO = ROOT / "backend" / "tests" / "fixtures" / "demo_video.mp4"
DEFAULT_RUN_ROOT = ROOT / ".runtime" / "demo-e2e"
ULTRALYTICS_ASSET_CANDIDATES = [
    ROOT / ".venv" / "lib" / "python3.9" / "site-packages" / "ultralytics" / "assets" / "bus.jpg",
    ROOT / ".venv" / "lib" / "python3.9" / "site-packages" / "ultralytics" / "assets" / "zidane.jpg",
]


@dataclass
class CommandRecord:
    label: str
    command: List[str]
    returncode: int
    elapsed_seconds: float
    stdout: str
    stderr: str


@dataclass
class CheckRecord:
    name: str
    ok: bool
    detail: str


@dataclass
class CaseReport:
    name: str
    session_id: str
    description: str
    checks: List[CheckRecord]
    commands: List[CommandRecord]
    latest_result: Dict[str, Any] | None
    tracking_state: Dict[str, Any]
    conversation_history: List[Dict[str, Any]]
    latency: Dict[str, Any] | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run demo_video.mp4 end-to-end tracking scenarios against the local Pi-backed robot agent."
    )
    parser.add_argument("--demo-video", default=str(DEFAULT_DEMO_VIDEO))
    parser.add_argument("--run-root", default=str(DEFAULT_RUN_ROOT))
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--tracker", default="bytetrack.yaml")
    parser.add_argument(
        "--case",
        action="append",
        dest="cases",
        default=None,
        help="Optional case filter. Repeat to run a subset of cases by name.",
    )
    return parser.parse_args()


def _ensure_demo_video(*, requested_path: Path, run_root: Path) -> Path:
    if requested_path.exists():
        return requested_path.resolve()

    fallback_image = next((path for path in ULTRALYTICS_ASSET_CANDIDATES if path.exists()), None)
    if fallback_image is None:
        raise FileNotFoundError(
            f"Demo video not found: {requested_path}\nNo fallback asset image was found under local ultralytics assets."
        )

    generated_video = run_root / "generated_demo_video.mp4"
    generated_video.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loop",
            "1",
            "-i",
            str(fallback_image),
            "-t",
            "6",
            "-r",
            "8",
            "-pix_fmt",
            "yuv420p",
            str(generated_video),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0 or not generated_video.exists():
        raise RuntimeError(
            f"Failed to generate fallback demo video from {fallback_image}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return generated_video.resolve()


def _check(ok: bool, name: str, detail: str) -> CheckRecord:
    return CheckRecord(name=name, ok=bool(ok), detail=detail)


def _run_command(*, label: str, command: List[str]) -> CommandRecord:
    started_at = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        returncode = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        returncode = 124
        stdout = exc.stdout or ""
        stderr = (exc.stderr or "") + "\nTimed out after 120 seconds."
    return CommandRecord(
        label=label,
        command=command,
        returncode=returncode,
        elapsed_seconds=round(time.monotonic() - started_at, 2),
        stdout=stdout,
        stderr=stderr,
    )


def _json_lines(text: str) -> List[Dict[str, Any]]:
    payloads: List[Dict[str, Any]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def _last_json_payload(text: str) -> Dict[str, Any]:
    payloads = _json_lines(text)
    if not payloads:
        raise ValueError(f"Command did not emit a JSON payload.\n{text}")
    return payloads[-1]


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _session_paths(state_root: Path, session_id: str) -> Dict[str, Path]:
    session_dir = state_root / "sessions" / session_id
    return {
        "session_dir": session_dir,
        "session_path": session_dir / "session.json",
    }


def _tracking_state(memory: Dict[str, Any]) -> tuple[Dict[str, Any], bool]:
    raw = dict(((memory.get("skill_cache") or {}).get("tracking") or {}))
    nested = raw.get("tracking")
    if len(raw) == 1 and isinstance(nested, dict):
        raw = dict(nested)
        had_nested = True
    else:
        had_nested = False
    normalized = dict(raw)
    if normalized.get("latest_target_id") in (None, "") and normalized.get("target_id") not in (None, ""):
        normalized["latest_target_id"] = normalized.get("target_id")
    if normalized.get("latest_memory") in (None, "") and normalized.get("memory") not in (None, ""):
        normalized["latest_memory"] = normalized.get("memory")
    if normalized.get("latest_target_crop") in (None, "") and normalized.get("crop_path") not in (None, ""):
        normalized["latest_target_crop"] = normalized.get("crop_path")
    return normalized, had_nested


def _wait_for_tracking_target(*, state_root: Path, session_id: str, timeout_seconds: float = 5.0) -> None:
    started = time.monotonic()
    session_path = _session_paths(state_root, session_id)["session_path"]
    while True:
        if session_path.exists():
            session = _load_json(session_path)
            tracking_state, _ = _tracking_state(session)
            if tracking_state.get("latest_target_id") not in (None, "") and tracking_state.get(
                "latest_confirmed_frame_path"
            ) not in (None, ""):
                return
        if time.monotonic() - started > timeout_seconds:
            raise TimeoutError(
                f"Timed out waiting for tracking state to settle for session {session_id}."
            )
        time.sleep(0.05)


def _load_session_and_tracking_state(
    *,
    state_root: Path,
    session_id: str,
    wait_for_memory: bool = False,
    timeout_seconds: float = 5.0,
    poll_interval_seconds: float = 0.1,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    paths = _session_paths(state_root, session_id)
    deadline = time.monotonic() + timeout_seconds
    last_session = _load_json(paths["session_path"])
    last_tracking_state, _ = _tracking_state(last_session)
    if not wait_for_memory:
        return last_session, last_tracking_state

    while True:
        session = _load_json(paths["session_path"])
        tracking_state, _ = _tracking_state(session)
        if tracking_state.get("latest_memory"):
            return session, tracking_state
        last_session = session
        last_tracking_state = tracking_state
        if time.monotonic() >= deadline:
            return last_session, last_tracking_state
        time.sleep(poll_interval_seconds)


def _tracking_memory_key(session: Dict[str, Any]) -> str:
    tracking_state, _ = _tracking_state(session)
    return json.dumps(tracking_state.get("latest_memory") or {}, ensure_ascii=False, sort_keys=True)


def _wait_for_memory_change(
    *,
    state_root: Path,
    session_id: str,
    previous_memory_key: str,
    timeout_seconds: float = 10.0,
    poll_interval_seconds: float = 0.1,
) -> float | None:
    deadline = time.monotonic() + timeout_seconds
    started = time.monotonic()
    session_path = _session_paths(state_root, session_id)["session_path"]
    while time.monotonic() < deadline:
        session = _load_json(session_path)
        if _tracking_memory_key(session) != previous_memory_key:
            return round(time.monotonic() - started, 2)
        time.sleep(poll_interval_seconds)
    return None


def _payload_model_elapsed_seconds(payload: Dict[str, Any]) -> float | None:
    tool_output = dict(payload.get("tool_output") or {})
    elapsed = tool_output.get("elapsed_seconds")
    if elapsed in (None, ""):
        return None
    return round(float(elapsed), 2)


def _prime_session(
    *,
    session_id: str,
    state_root: Path,
    output_dir: Path,
    demo_video: Path,
    device: str,
    tracker: str,
    max_events: int,
) -> CommandRecord:
    return _run_command(
        label=f"{session_id}: perception",
        command=[
            "uv",
            "run",
            "python",
            "-m",
            "scripts.run_tracking_perception",
            "--source",
            str(demo_video),
            "--session-id",
            session_id,
            "--state-root",
            str(state_root),
            "--output-dir",
            str(output_dir),
            "--device",
            device,
            "--tracker",
            tracker,
            "--interval-seconds",
            "1",
            "--max-events",
            str(max_events),
        ],
    )


def _chat_turn(
    *,
    session_id: str,
    state_root: Path,
    artifacts_root: Path,
    text: str,
) -> CommandRecord:
    return _run_command(
        label=f"{session_id}: chat: {text}",
        command=[
        "uv",
        "run",
        "robot-agent",
        "chat",
        "--session-id",
        session_id,
        "--state-root",
        str(state_root),
        "--artifacts-root",
        str(artifacts_root),
        "--text",
        text,
        ],
    )


def _loop_turn(
    *,
    session_id: str,
    state_root: Path,
    artifacts_root: Path,
) -> CommandRecord:
    return _run_command(
        label=f"{session_id}: tracking loop",
        command=[
            "uv",
            "run",
            "python",
            "-m",
            "backend.tracking.loop",
            "--session-id",
            session_id,
            "--state-root",
            str(state_root),
            "--artifacts-root",
            str(artifacts_root),
            "--interval-seconds",
            "0.2",
            "--idle-sleep-seconds",
            "0.1",
            "--max-turns",
            "1",
        ],
    )


def _direct_track_turn(
    *,
    session_id: str,
    state_root: Path,
    artifacts_root: Path,
    text: str = "继续跟踪",
) -> CommandRecord:
    return _run_command(
        label=f"{session_id}: tracking-track: {text}",
        command=[
            "uv",
            "run",
            "robot-agent",
            "tracking-track",
            "--session-id",
            session_id,
            "--state-root",
            str(state_root),
            "--artifacts-root",
            str(artifacts_root),
            "--text",
            text,
        ],
    )


def _case_report(
    *,
    name: str,
    description: str,
    session_id: str,
    state_root: Path,
    commands: List[CommandRecord],
    checks: List[CheckRecord],
    latency: Dict[str, Any] | None = None,
) -> CaseReport:
    paths = _session_paths(state_root, session_id)
    session = _load_json(paths["session_path"])
    tracking_state, _ = _tracking_state(session)
    return CaseReport(
        name=name,
        session_id=session_id,
        description=description,
        checks=checks,
        commands=commands,
        latest_result=session.get("latest_result"),
        tracking_state=tracking_state,
        conversation_history=list(session.get("conversation_history") or []),
        latency=latency,
    )


def _assert_command_ok(record: CommandRecord) -> None:
    if record.returncode == 0:
        return
    raise RuntimeError(
        f"{record.label} failed with exit code {record.returncode}\n"
        f"stdout:\n{record.stdout}\n"
        f"stderr:\n{record.stderr}"
    )


def _run_small_context_case(
    *,
    state_root: Path,
    output_dir: Path,
    artifacts_root: Path,
    demo_video: Path,
    device: str,
    tracker: str,
) -> CaseReport:
    session_id = "case_small_context"
    commands = [
        _prime_session(
            session_id=session_id,
            state_root=state_root,
            output_dir=output_dir,
            demo_video=demo_video,
            device=device,
            tracker=tracker,
            max_events=2,
        )
    ]
    commands.append(
        _chat_turn(
            session_id=session_id,
            state_root=state_root,
            artifacts_root=artifacts_root,
            text="开始跟踪穿黑衣服的人。",
        )
    )
    for command in commands:
        _assert_command_ok(command)

    turn_payload = _last_json_payload(commands[-1].stdout)
    paths = _session_paths(state_root, session_id)
    session = _load_json(paths["session_path"])
    tracking_state, had_nested_tracking = _tracking_state(session)
    latest_result = session.get("latest_result") or {}
    checks = [
        _check(turn_payload.get("status") == "processed", "turn processed", f"status={turn_payload.get('status')}"),
        _check(turn_payload.get("skill_name") == "tracking", "tracking state owner selected", f"skill={turn_payload.get('skill_name')}"),
        _check(latest_result.get("target_id") not in (None, ""), "target initialized", f"target_id={latest_result.get('target_id')}"),
        _check(tracking_state.get("latest_target_id") not in (None, ""), "memory target updated", f"memory.latest_target_id={tracking_state.get('latest_target_id')}"),
        _check(not had_nested_tracking, "skill state shape is flat", f"nested_tracking_wrapper={had_nested_tracking}"),
    ]
    return _case_report(
        name="small_context_explicit_target",
        description="Minimal context, one explicit target-selection turn.",
        session_id=session_id,
        state_root=state_root,
        commands=commands,
        checks=checks,
    )


def _run_large_context_case(
    *,
    state_root: Path,
    output_dir: Path,
    artifacts_root: Path,
    demo_video: Path,
    device: str,
    tracker: str,
) -> CaseReport:
    session_id = "case_large_context"
    commands = [
        _prime_session(
            session_id=session_id,
            state_root=state_root,
            output_dir=output_dir,
            demo_video=demo_video,
            device=device,
            tracker=tracker,
            max_events=6,
        )
    ]
    for text in (
        "先不要开始跟踪，只简短告诉我当前候选人的 ID。",
        "如果我之后要继续跟踪，你会更依赖外观还是位置？一句话回答。",
        "我之后可能会问你他现在在哪里，先记住这个上下文。",
        "现在开始跟踪 ID 为 1 的人。",
    ):
        commands.append(
            _chat_turn(
                session_id=session_id,
                state_root=state_root,
                artifacts_root=artifacts_root,
                text=text,
            )
        )
    for command in commands:
        _assert_command_ok(command)

    final_turn = _last_json_payload(commands[-1].stdout)
    session, tracking_state = _load_session_and_tracking_state(
        state_root=state_root,
        session_id=session_id,
        wait_for_memory=True,
    )
    checks = [
        _check(
            all(_last_json_payload(command.stdout).get("status") in {"processed", "idle"} for command in commands[1:-1]),
            "prelude turns stayed valid",
            "all prelude turns returned processed or idle",
        ),
        _check(final_turn.get("status") == "processed", "final turn processed", f"status={final_turn.get('status')}"),
        _check(session.get("latest_result", {}).get("target_id") == 1, "large-context init kept the right target", f"target_id={session.get('latest_result', {}).get('target_id')}"),
        _check(len(session.get("conversation_history") or []) >= 5, "conversation history persisted", f"history_len={len(session.get('conversation_history') or [])}"),
        _check(bool(tracking_state.get("latest_memory")), "tracking memory exists", "memory captured after init"),
    ]
    return _case_report(
        name="large_context_then_target",
        description="Several prelude chat turns before explicit target selection.",
        session_id=session_id,
        state_root=state_root,
        commands=commands,
        checks=checks,
    )


def _run_chat_then_target_case(
    *,
    state_root: Path,
    output_dir: Path,
    artifacts_root: Path,
    demo_video: Path,
    device: str,
    tracker: str,
) -> CaseReport:
    session_id = "case_chat_then_target"
    commands = [
        _prime_session(
            session_id=session_id,
            state_root=state_root,
            output_dir=output_dir,
            demo_video=demo_video,
            device=device,
            tracker=tracker,
            max_events=6,
        ),
        _chat_turn(
            session_id=session_id,
            state_root=state_root,
            artifacts_root=artifacts_root,
            text="先别跟踪，告诉我当前这个人更偏画面左边、中间还是右边。",
        ),
        _chat_turn(
            session_id=session_id,
            state_root=state_root,
            artifacts_root=artifacts_root,
            text="好的，现在开始跟踪 ID 为 1 的人。",
        ),
    ]
    for command in commands:
        _assert_command_ok(command)

    first_turn = _last_json_payload(commands[1].stdout)
    second_turn = _last_json_payload(commands[2].stdout)
    session = _load_json(_session_paths(state_root, session_id)["session_path"])
    checks = [
        _check(first_turn.get("status") == "processed", "pre-target reply worked", f"status={first_turn.get('status')}"),
        _check(second_turn.get("status") == "processed", "target turn processed", f"status={second_turn.get('status')}"),
        _check(session.get("latest_result", {}).get("target_id") == 1, "target selected after chat", f"target_id={session.get('latest_result', {}).get('target_id')}"),
    ]
    return _case_report(
        name="chat_first_then_target",
        description="Ask a visual chat question first, then explicitly lock a target.",
        session_id=session_id,
        state_root=state_root,
        commands=commands,
        checks=checks,
    )


def _run_continuous_tracking_case(
    *,
    state_root: Path,
    output_dir: Path,
    artifacts_root: Path,
    demo_video: Path,
    device: str,
    tracker: str,
) -> CaseReport:
    session_id = "case_continuous_tracking"
    commands = [
        _prime_session(
            session_id=session_id,
            state_root=state_root,
            output_dir=output_dir,
            demo_video=demo_video,
            device=device,
            tracker=tracker,
            max_events=2,
        ),
        _direct_init_turn(
            session_id=session_id,
            state_root=state_root,
            artifacts_root=artifacts_root,
            text="开始跟踪穿黑衣服的人。",
        ),
        _prime_session(
            session_id=session_id,
            state_root=state_root,
            output_dir=output_dir,
            demo_video=demo_video,
            device=device,
            tracker=tracker,
            max_events=3,
        ),
        _loop_turn(
            session_id=session_id,
            state_root=state_root,
            artifacts_root=artifacts_root,
        ),
    ]
    for command in commands:
        _assert_command_ok(command)

    _wait_for_tracking_target(state_root=state_root, session_id=session_id)

    loop_events = _json_lines(commands[-1].stdout)
    loop_payload = loop_events[-1] if loop_events else {}
    saw_tracking_bound = any(
        str(event.get("status", "")).strip() == "tracking_bound" for event in loop_events
    )
    saw_processed_tracking = any(
        str(event.get("status", "")).strip() == "processed"
        and str(event.get("skill_name", "")).strip() == "tracking"
        for event in loop_events
    )
    paths = _session_paths(state_root, session_id)
    session = _load_json(paths["session_path"])
    tracking_state, _ = _tracking_state(session)
    expected_target_id = tracking_state.get("latest_target_id")
    latest_frame_id = loop_payload.get("frame_id") or (session.get("latest_result") or {}).get("frame_id")
    checks = [
        _check(
            saw_processed_tracking or saw_tracking_bound,
            "loop advanced tracking",
            f"statuses={[event.get('status') for event in loop_events]}",
        ),
        _check(
            saw_processed_tracking
            or (
                saw_tracking_bound
                and str(loop_payload.get("status", "")).strip() in {"tracking_bound", "completed"}
            ),
            "loop stayed on tracking",
            f"final_status={loop_payload.get('status')} skill={loop_payload.get('skill_name')}",
        ),
        _check(tracking_state.get("latest_target_id") == expected_target_id, "active target persisted", f"memory.latest_target_id={tracking_state.get('latest_target_id')}"),
        _check(
            latest_frame_id == "frame_000005",
            "loop reached the newest sampled frame",
            f"frame_id={latest_frame_id}",
        ),
    ]
    return _case_report(
        name="continuous_tracking_loop",
        description="Initialize a target, ingest newer observations, then let the loop drive one continue-tracking turn.",
        session_id=session_id,
        state_root=state_root,
        commands=commands,
        checks=checks,
    )


def _run_tracking_chat_case(
    *,
    state_root: Path,
    output_dir: Path,
    artifacts_root: Path,
    demo_video: Path,
    device: str,
    tracker: str,
) -> CaseReport:
    session_id = "case_tracking_chat"
    commands = [
        _prime_session(
            session_id=session_id,
            state_root=state_root,
            output_dir=output_dir,
            demo_video=demo_video,
            device=device,
            tracker=tracker,
            max_events=6,
        ),
        _chat_turn(
            session_id=session_id,
            state_root=state_root,
            artifacts_root=artifacts_root,
            text="开始跟踪 ID 为 1 的人。",
        ),
        _chat_turn(
            session_id=session_id,
            state_root=state_root,
            artifacts_root=artifacts_root,
            text="他现在在哪里？",
        ),
        _chat_turn(
            session_id=session_id,
            state_root=state_root,
            artifacts_root=artifacts_root,
            text="还在跟踪同一个人吗？",
        ),
    ]
    for command in commands:
        _assert_command_ok(command)

    where_payload = _last_json_payload(commands[2].stdout)
    same_target_payload = _last_json_payload(commands[3].stdout)
    session = _load_json(_session_paths(state_root, session_id)["session_path"])
    tracking_state, _ = _tracking_state(session)
    checks = [
        _check(where_payload.get("status") == "processed", "where-question answered", f"status={where_payload.get('status')}"),
        _check(same_target_payload.get("status") == "processed", "same-target question answered", f"status={same_target_payload.get('status')}"),
        _check(bool((session.get("latest_result") or {}).get("text")), "latest textual answer is non-empty", f"text={(session.get('latest_result') or {}).get('text', '')}"),
        _check(tracking_state.get("latest_target_id") == 1, "tracking memory still points to target 1", f"memory.latest_target_id={tracking_state.get('latest_target_id')}"),
    ]
    return _case_report(
        name="tracking_chat_qa",
        description="Ask follow-up questions after a target is already active.",
        session_id=session_id,
        state_root=state_root,
        commands=commands,
        checks=checks,
    )


def _run_invalid_target_case(
    *,
    state_root: Path,
    output_dir: Path,
    artifacts_root: Path,
    demo_video: Path,
    device: str,
    tracker: str,
) -> CaseReport:
    session_id = "case_invalid_target"
    commands = [
        _prime_session(
            session_id=session_id,
            state_root=state_root,
            output_dir=output_dir,
            demo_video=demo_video,
            device=device,
            tracker=tracker,
            max_events=6,
        ),
        _chat_turn(
            session_id=session_id,
            state_root=state_root,
            artifacts_root=artifacts_root,
            text="请跟踪 ID 为 99 的人。",
        ),
    ]
    for command in commands:
        _assert_command_ok(command)

    session = _load_json(_session_paths(state_root, session_id)["session_path"])
    latest_result = session.get("latest_result") or {}
    checks = [
        _check(latest_result.get("found") is False, "invalid target was not hallucinated", f"found={latest_result.get('found')}"),
        _check(
            bool(latest_result.get("needs_clarification") or latest_result.get("clarification_question")),
            "invalid target triggered clarification",
            f"clarification_question={latest_result.get('clarification_question')}",
        ),
    ]
    return _case_report(
        name="invalid_target_clarification",
        description="Explicitly request a non-existent target ID and ensure the agent asks to clarify.",
        session_id=session_id,
        state_root=state_root,
        commands=commands,
        checks=checks,
    )


def _run_init_latency_case(
    *,
    state_root: Path,
    output_dir: Path,
    artifacts_root: Path,
    demo_video: Path,
    device: str,
    tracker: str,
) -> CaseReport:
    session_id = "case_init_latency"
    commands = [
        _prime_session(
            session_id=session_id,
            state_root=state_root,
            output_dir=output_dir,
            demo_video=demo_video,
            device=device,
            tracker=tracker,
            max_events=2,
        )
    ]
    previous_memory_key = "{}"
    commands.append(
        _chat_turn(
            session_id=session_id,
            state_root=state_root,
            artifacts_root=artifacts_root,
            text="开始跟踪穿黑衣服的人。",
        )
    )
    for command in commands:
        _assert_command_ok(command)

    payload = _last_json_payload(commands[-1].stdout)
    rewrite_seconds = _wait_for_memory_change(
        state_root=state_root,
        session_id=session_id,
        previous_memory_key=previous_memory_key,
    )
    model_seconds = _payload_model_elapsed_seconds(payload)
    total_seconds = commands[-1].elapsed_seconds
    latency = {
        "kind": "init",
        "total_seconds": total_seconds,
        "model_seconds": model_seconds,
        "non_model_overhead_seconds": round(total_seconds - model_seconds, 2) if model_seconds is not None else None,
        "async_rewrite_seconds": rewrite_seconds,
    }
    session, tracking_state = _load_session_and_tracking_state(
        state_root=state_root,
        session_id=session_id,
        wait_for_memory=True,
    )
    checks = [
        _check(payload.get("status") == "processed", "init turn processed", f"status={payload.get('status')}"),
        _check(payload.get("tool") == "init", "init tool used", f"tool={payload.get('tool')}"),
        _check((session.get("latest_result") or {}).get("target_id") not in (None, ""), "target selected", f"target_id={(session.get('latest_result') or {}).get('target_id')}"),
        _check(bool(tracking_state.get("latest_memory")), "init rewrite completed", f"rewrite_seconds={rewrite_seconds}"),
    ]
    return _case_report(
        name="init_latency_breakdown",
        description="Measure one init turn total latency, model latency, and async rewrite completion latency.",
        session_id=session_id,
        state_root=state_root,
        commands=commands,
        checks=checks,
        latency=latency,
    )


def _run_track_latency_case(
    *,
    state_root: Path,
    output_dir: Path,
    artifacts_root: Path,
    demo_video: Path,
    device: str,
    tracker: str,
) -> CaseReport:
    session_id = "case_track_latency"
    commands = [
        _prime_session(
            session_id=session_id,
            state_root=state_root,
            output_dir=output_dir,
            demo_video=demo_video,
            device=device,
            tracker=tracker,
            max_events=3,
        ),
        _chat_turn(
            session_id=session_id,
            state_root=state_root,
            artifacts_root=artifacts_root,
            text="开始跟踪穿黑衣服的人。",
        ),
        _prime_session(
            session_id=session_id,
            state_root=state_root,
            output_dir=output_dir,
            demo_video=demo_video,
            device=device,
            tracker=tracker,
            max_events=2,
        ),
    ]
    for command in commands:
        _assert_command_ok(command)

    session_before_track, tracking_state_before_track = _load_session_and_tracking_state(
        state_root=state_root,
        session_id=session_id,
        wait_for_memory=True,
    )
    expected_target_id = tracking_state_before_track.get("latest_target_id")
    previous_memory_key = _tracking_memory_key(session_before_track)
    commands.append(
        _direct_track_turn(
            session_id=session_id,
            state_root=state_root,
            artifacts_root=artifacts_root,
        )
    )
    _assert_command_ok(commands[-1])

    payload = _last_json_payload(commands[-1].stdout)
    rewrite_seconds = _wait_for_memory_change(
        state_root=state_root,
        session_id=session_id,
        previous_memory_key=previous_memory_key,
    )
    model_seconds = _payload_model_elapsed_seconds(payload)
    total_seconds = commands[-1].elapsed_seconds
    latency = {
        "kind": "track",
        "total_seconds": total_seconds,
        "model_seconds": model_seconds,
        "non_model_overhead_seconds": round(total_seconds - model_seconds, 2) if model_seconds is not None else None,
        "async_rewrite_seconds": rewrite_seconds,
        "previous_memory_summary": tracking_state_before_track.get("memory_summary"),
    }
    session_after_track, tracking_state_after_track = _load_session_and_tracking_state(
        state_root=state_root,
        session_id=session_id,
        wait_for_memory=False,
    )
    checks = [
        _check(payload.get("status") == "processed", "track turn processed", f"status={payload.get('status')}"),
        _check(payload.get("tool") == "track", "track tool used", f"tool={payload.get('tool')}"),
        _check((session_after_track.get("latest_result") or {}).get("target_id") == expected_target_id, "target stayed bound", f"target_id={(session_after_track.get('latest_result') or {}).get('target_id')}"),
        _check(
            rewrite_seconds is not None or bool(tracking_state_after_track.get("latest_memory")),
            "track rewrite completed or memory remained available",
            f"rewrite_seconds={rewrite_seconds}",
        ),
    ]
    return _case_report(
        name="track_latency_breakdown",
        description="Measure one deterministic track step total latency, model latency, and async rewrite completion latency.",
        session_id=session_id,
        state_root=state_root,
        commands=commands,
        checks=checks,
        latency=latency,
    )


def _case_passed(report: CaseReport) -> bool:
    return all(check.ok for check in report.checks)


def _truncate_block(text: str, limit: int = 1200) -> str:
    normalized = text.strip()
    if not normalized:
        return ""
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "\n... [truncated]"


def _json_block(payload: Any) -> str:
    if payload in (None, {}, []):
        return "null"
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _render_markdown(summary: Dict[str, Any], reports: List[CaseReport]) -> str:
    lines: List[str] = []
    lines.append("# Demo Tracking E2E Report")
    lines.append("")
    lines.append(f"- Demo video: `{summary['demo_video']}`")
    lines.append(f"- Run root: `{summary['run_root']}`")
    lines.append(f"- Passed cases: **{summary['passed_cases']} / {summary['total_cases']}**")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Case | Status |")
    lines.append("| --- | --- |")
    for report in reports:
        lines.append(f"| `{report.name}` | {'PASS' if _case_passed(report) else 'FAIL'} |")
    for report in reports:
        lines.append("")
        lines.append(f"## {report.name}")
        lines.append("")
        lines.append(f"- Session: `{report.session_id}`")
        lines.append(f"- Description: {report.description}")
        lines.append(f"- Status: **{'PASS' if _case_passed(report) else 'FAIL'}**")
        lines.append("")
        lines.append("### Checks")
        lines.append("")
        for check in report.checks:
            marker = "PASS" if check.ok else "FAIL"
            lines.append(f"- [{marker}] {check.name}: `{check.detail}`")
        lines.append("")
        lines.append("### Latest Result")
        lines.append("")
        lines.append("```json")
        lines.append(_json_block(report.latest_result))
        lines.append("```")
        lines.append("")
        lines.append("### Tracking State")
        lines.append("")
        lines.append("```json")
        lines.append(_json_block(report.tracking_state))
        lines.append("```")
        if report.latency:
            lines.append("")
            lines.append("### Latency")
            lines.append("")
            lines.append("```json")
            lines.append(_json_block(report.latency))
            lines.append("```")
        if report.conversation_history:
            lines.append("")
            lines.append("### Conversation History")
            lines.append("")
            for item in report.conversation_history:
                role = str(item.get("role", "unknown"))
                text = str(item.get("text", ""))
                lines.append(f"- **{role}**: {text}")
        if report.commands:
            lines.append("")
            lines.append("### Commands")
            lines.append("")
            for command in report.commands:
                lines.append(f"#### {command.label}")
                lines.append("")
                lines.append(f"- Return code: `{command.returncode}`")
                lines.append(f"- Elapsed seconds: `{command.elapsed_seconds}`")
                lines.append("")
                lines.append("```bash")
                lines.append(" ".join(command.command))
                lines.append("```")
                stdout = _truncate_block(command.stdout)
                stderr = _truncate_block(command.stderr)
                if stdout:
                    lines.append("")
                    lines.append("stdout:")
                    lines.append("```text")
                    lines.append(stdout)
                    lines.append("```")
                if stderr:
                    lines.append("")
                    lines.append("stderr:")
                    lines.append("```text")
                    lines.append(stderr)
                    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def _render_html(markdown_text: str, html_path: Path) -> None:
    try:
        result = subprocess.run(
            ["pandoc", "-f", "gfm", "-t", "html5", "-s", "-o", str(html_path)],
            input=markdown_text,
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        result = None
    if result is not None and result.returncode == 0 and html_path.exists():
        return
    fallback = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>Demo Tracking E2E Report</title>"
        "<style>body{font-family:ui-monospace,Menlo,monospace;max-width:1000px;margin:40px auto;padding:0 20px;line-height:1.6}"
        "pre{white-space:pre-wrap;background:#f5f5f5;padding:12px;border-radius:8px}"
        "code{font-family:inherit}</style></head><body><pre>"
        + html.escape(markdown_text)
        + "</pre></body></html>"
    )
    html_path.write_text(fallback, encoding="utf-8")


def _render_pdf(html_path: Path, pdf_path: Path) -> bool:
    try:
        result = subprocess.run(
            ["playwright", "pdf", html_path.as_uri(), str(pdf_path)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0 and pdf_path.exists()


def _write_human_reports(*, run_root: Path, summary: Dict[str, Any], reports: List[CaseReport]) -> Dict[str, str]:
    markdown_text = _render_markdown(summary, reports)
    markdown_path = run_root / "report.md"
    html_path = run_root / "report.html"
    pdf_path = run_root / "report.pdf"
    markdown_path.write_text(markdown_text, encoding="utf-8")
    _render_html(markdown_text, html_path)
    pdf_created = _render_pdf(html_path, pdf_path)
    paths = {
        "report_json_path": str((run_root / "report.json")),
        "report_md_path": str(markdown_path),
        "report_html_path": str(html_path),
    }
    if pdf_created:
        paths["report_pdf_path"] = str(pdf_path)
    return paths


def main() -> int:
    args = parse_args()
    run_root = Path(args.run_root).resolve()
    if run_root.exists():
        shutil.rmtree(run_root)
    run_root.mkdir(parents=True, exist_ok=True)
    demo_video = _ensure_demo_video(
        requested_path=Path(args.demo_video),
        run_root=run_root,
    )
    state_root = run_root / "state"
    output_dir = run_root / "perception"
    artifacts_root = run_root / "artifacts"
    report_path = run_root / "report.json"

    cases = [
        (
            "small_context_explicit_target",
            "case_small_context",
            "Minimal context, one explicit backend init turn.",
            _run_small_context_case,
        ),
        (
            "continuous_tracking_loop",
            "case_continuous_tracking",
            "Initialize a target through backend init, ingest newer observations, then let the loop drive one deterministic track step.",
            _run_continuous_tracking_case,
        ),
        (
            "init_latency_breakdown",
            "case_init_latency",
            "Measure one backend init turn latency and async rewrite completion.",
            _run_init_latency_case,
        ),
        (
            "track_latency_breakdown",
            "case_track_latency",
            "Measure one deterministic track step latency and async rewrite completion.",
            _run_track_latency_case,
        ),
        (
            "invalid_target_clarification",
            "case_invalid_target",
            "Explicitly request a non-existent target ID and ensure backend init asks to clarify.",
            _run_invalid_target_case,
        ),
    ]
    requested_case_names = {str(name).strip() for name in list(args.cases or []) if str(name).strip()}
    if requested_case_names:
        cases = [case for case in cases if case[0] in requested_case_names]
        if not cases:
            raise ValueError(f"No matching cases for --case. Requested: {sorted(requested_case_names)}")

    reports: List[CaseReport] = []
    for case_name, session_id, description, case in cases:
        print(
            json.dumps(
                {"event": "case_start", "name": case_name, "session_id": session_id},
                ensure_ascii=True,
            ),
            flush=True,
        )
        try:
            report = (
                case(
                    state_root=state_root,
                    output_dir=output_dir,
                    artifacts_root=artifacts_root,
                    demo_video=demo_video,
                    device=args.device,
                    tracker=args.tracker,
                )
            )
            reports.append(report)
        except Exception as exc:
            report = CaseReport(
                name=case_name,
                session_id=session_id,
                description=description,
                checks=[_check(False, "case execution", str(exc))],
                commands=[],
                latest_result=None,
                tracking_state={},
                conversation_history=[],
            )
            reports.append(report)
        print(
            json.dumps(
                {
                    "event": "case_end",
                    "name": case_name,
                    "passed": all(check.ok for check in report.checks),
                },
                ensure_ascii=True,
            ),
            flush=True,
        )

    summary = {
        "demo_video": str(demo_video),
        "run_root": str(run_root),
        "passed_cases": sum(1 for report in reports if all(check.ok for check in report.checks)),
        "total_cases": len(reports),
        "latency_reports": {
            report.name: report.latency
            for report in reports
            if report.latency is not None
        },
        "cases": [
            {
                **asdict(report),
                "checks": [asdict(check) for check in report.checks],
                "commands": [asdict(command) for command in report.commands],
            }
            for report in reports
        ],
    }
    report_path.write_text(json.dumps(summary, indent=2, ensure_ascii=True), encoding="utf-8")
    human_report_paths = _write_human_reports(run_root=run_root, summary=summary, reports=reports)

    print(
        json.dumps(
            {
                "report_path": str(report_path),
                "passed_cases": summary["passed_cases"],
                "total_cases": summary["total_cases"],
                **human_report_paths,
            },
            ensure_ascii=True,
        )
    )
    return 0 if summary["passed_cases"] == summary["total_cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
