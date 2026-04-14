from __future__ import annotations

import importlib.util
from pathlib import Path

from PIL import Image

from agent.runner import run_ordinary_skill_turn
from agent.session import AgentSessionStore
from capabilities.tracking.runtime.context import TRACKING_LIFECYCLE_STOPPED
from capabilities.tracking.runtime.effects import (
    PENDING_REWRITE_ENQUEUED_AT_KEY,
    PENDING_REWRITE_INPUT_KEY,
    PENDING_REWRITE_REQUEST_ID_KEY,
)
from capabilities.tracking.state.memory import read_tracking_memory_snapshot, write_tracking_memory_snapshot


ROOT = Path(__file__).resolve().parents[1]


def _load_script_module(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _frame_image(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 48), color="white").save(path, format="JPEG")
    return path


def test_tracking_stop_helper_clears_tracking_state_and_memory(tmp_path: Path) -> None:
    stop_turn = _load_script_module(
        ROOT / "skills" / "tracking-stop" / "scripts" / "stop_turn.py",
        "test_tracking_stop_turn",
    )
    state_root = tmp_path / "state"
    sessions = AgentSessionStore(state_root)
    sessions.start_fresh_session("sess_tracking", device_id="robot_01")
    sessions.append_chat_request(
        session_id="sess_tracking",
        device_id="robot_01",
        text="停止跟踪",
        request_id="req_stop",
    )
    sessions.patch_skill_state(
        "sess_tracking",
        skill_name="tracking",
        patch={
            "target_description": "穿黑衣服的人",
            "latest_target_id": 15,
            "pending_question": "请确认目标。",
            "lifecycle_status": "bound",
            "next_tracking_turn_at": 123.0,
            PENDING_REWRITE_INPUT_KEY: {"target_id": 15, "frame_id": "frame_000001"},
            PENDING_REWRITE_REQUEST_ID_KEY: "req_init",
            PENDING_REWRITE_ENQUEUED_AT_KEY: 456.0,
        },
    )
    crop_path = _frame_image(tmp_path / "memory" / "front.jpg")
    write_tracking_memory_snapshot(
        state_root=state_root,
        session_id="sess_tracking",
        memory={
            "core": "黑色上衣，黑框眼镜。",
            "front_view": "正面戴眼镜。",
            "back_view": "",
            "distinguish": "唯一近距离人物。",
        },
        crop_path=crop_path,
        reference_view="front",
    )

    payload = stop_turn.run_stop_turn(
        session_id="sess_tracking",
        state_root=state_root,
        env_file=tmp_path / ".ENV",
    )
    session = sessions.load("sess_tracking")
    memory_snapshot = read_tracking_memory_snapshot(state_root=state_root, session_id="sess_tracking")

    assert payload["skill_name"] == "tracking-stop"
    assert payload["tool"] == "stop"
    assert payload["session_result"]["behavior"] == "stop"
    assert payload["session_result"]["text"] == "已停止跟踪当前目标。"
    assert session.latest_result is None
    assert session.capabilities["tracking"]["latest_target_id"] is None
    assert session.capabilities["tracking"]["pending_question"] is None
    assert session.capabilities["tracking"]["next_tracking_turn_at"] is None
    assert session.capabilities["tracking"]["lifecycle_status"] == TRACKING_LIFECYCLE_STOPPED
    assert session.capabilities["tracking"]["stop_reason"] == "manual_stop"
    assert session.capabilities["tracking"][PENDING_REWRITE_INPUT_KEY] is None
    assert session.capabilities["tracking"][PENDING_REWRITE_REQUEST_ID_KEY] is None
    assert memory_snapshot["memory"]["core"] == ""
    assert memory_snapshot["front_crop_path"] == ""


def test_tracking_stop_helper_returns_idle_message_when_nothing_is_running(tmp_path: Path) -> None:
    stop_turn = _load_script_module(
        ROOT / "skills" / "tracking-stop" / "scripts" / "stop_turn.py",
        "test_tracking_stop_turn_idle",
    )
    state_root = tmp_path / "state"
    sessions = AgentSessionStore(state_root)
    sessions.start_fresh_session("sess_tracking", device_id="robot_01")
    sessions.append_chat_request(
        session_id="sess_tracking",
        device_id="robot_01",
        text="停止跟踪",
        request_id="req_stop",
    )

    payload = stop_turn.run_stop_turn(
        session_id="sess_tracking",
        state_root=state_root,
        env_file=tmp_path / ".ENV",
    )
    session = sessions.load("sess_tracking")

    assert payload["skill_name"] == "tracking-stop"
    assert payload["session_result"]["text"] == "当前没有进行中的跟踪。"
    assert session.capabilities == {}


def test_runner_commits_tracking_stop_skill_result(tmp_path: Path) -> None:
    stop_turn = _load_script_module(
        ROOT / "skills" / "tracking-stop" / "scripts" / "stop_turn.py",
        "test_tracking_stop_turn_runner",
    )
    state_root = tmp_path / "state"
    sessions = AgentSessionStore(state_root)
    sessions.start_fresh_session("sess_tracking", device_id="robot_01")
    sessions.append_chat_request(
        session_id="sess_tracking",
        device_id="robot_01",
        text="停止跟踪",
        request_id="req_stop",
    )
    sessions.patch_skill_state(
        "sess_tracking",
        skill_name="tracking",
        patch={
            "target_description": "穿黑衣服的人",
            "latest_target_id": 15,
            "lifecycle_status": "bound",
            "next_tracking_turn_at": 123.0,
        },
    )

    payload = run_ordinary_skill_turn(
        sessions=sessions,
        session_id="sess_tracking",
        skill_name="tracking-stop",
        env_file=tmp_path / ".ENV",
        build_payload=lambda session, request_id, stale_guard: stop_turn.run_stop_turn(
            session_id=session.session_id,
            state_root=state_root,
            env_file=tmp_path / ".ENV",
            bound_session=session,
            request_id=request_id,
            stale_guard=stale_guard,
        ),
    )
    session = sessions.load("sess_tracking")

    assert payload["status"] == "processed"
    assert payload["skill_name"] == "tracking-stop"
    assert session.latest_result["behavior"] == "stop"
    assert session.latest_result["text"] == "已停止跟踪当前目标。"
    assert session.capabilities["tracking"]["latest_target_id"] is None
    assert session.capabilities["tracking"]["lifecycle_status"] == TRACKING_LIFECYCLE_STOPPED
