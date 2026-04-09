from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

from PIL import Image

from backend.runtime_session import AgentSessionStore
from backend.perception import LocalPerceptionService, RobotDetection, RobotFrame, RobotIngestEvent
from backend.persistence import ActiveSessionStore, LiveSessionStore
from backend.system1 import LocalSystem1Service
from backend.tracking.memory import write_tracking_memory_snapshot
from viewer.stream import build_agent_viewer_payload


def _memory_payload() -> dict:
    return {
        "core": "短发、黑色上衣。",
        "front_view": "正面短发，黑色上衣。",
        "back_view": "",
        "distinguish": "和旁边浅色上衣的人区分时优先看黑色上衣。",
    }


def _tiny_jpeg_base64() -> str:
    buffer = BytesIO()
    Image.new("RGB", (8, 8), color="white").save(buffer, format="JPEG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _frame_image(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), color="white").save(path, format="JPEG")
    return path


def _write_environment_frame(
    *,
    state_root: Path,
    session_id: str,
    frame_id: str,
    timestamp_ms: int,
    image_path: Path,
    detections: list[dict[str, object]],
    text: str = "观察画面",
) -> None:
    perception = LocalPerceptionService(state_root)
    system1 = LocalSystem1Service(state_root)
    perception.write_observation(
        RobotIngestEvent(
            session_id=session_id,
            device_id="robot_01",
            frame=RobotFrame(
                frame_id=frame_id,
                timestamp_ms=timestamp_ms,
                image_path=str(image_path),
            ),
            detections=[
                RobotDetection(
                    track_id=int(detection["track_id"]),
                    bbox=[int(value) for value in detection["bbox"]],
                    score=float(detection.get("score", 1.0)),
                )
                for detection in detections
            ],
            text=text,
        ),
    )
    system1.write_result(
        {
            "frame_id": frame_id,
            "timestamp_ms": timestamp_ms,
            "image_path": str(image_path),
            "detections": list(detections),
        }
    )


def _write_tracking_memory(state_root: Path, session_id: str) -> None:
    write_tracking_memory_snapshot(
        state_root=state_root,
        session_id=session_id,
        memory=_memory_payload(),
        reset=True,
    )


def test_build_agent_viewer_payload_includes_current_frame_memory_and_history(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    store = LiveSessionStore(state_root)
    perception = LocalPerceptionService(state_root)
    frame_path = _frame_image(tmp_path / "frame.jpg")
    perception.write_observation(
        RobotIngestEvent(
            session_id="sess_001",
            device_id="robot_01",
            frame=RobotFrame(
                frame_id="frame_000001",
                timestamp_ms=1710000000000,
                image_path=str(frame_path),
            ),
            detections=[RobotDetection(track_id=3, bbox=[10, 20, 30, 40], score=0.95)],
            text="先看看画面",
        ),
    )
    store.append_chat_request(
        session_id="sess_001",
        device_id="robot_01",
        text="先看看画面",
        request_id="req_001",
    )
    store.apply_agent_result(
        "sess_001",
        {
            "request_id": "req_001",
            "function": "tracking",
            "behavior": "reply",
            "frame_id": "frame_000001",
            "target_id": 3,
            "bbox": [10, 20, 30, 40],
            "text": "目标在左侧。",
            "memory": _memory_payload(),
        },
    )
    AgentSessionStore(state_root).patch_skill_state(
        "sess_001",
        skill_name="tracking",
        patch={
            "latest_target_id": 3,
            "pending_question": "",
        },
    )
    _write_tracking_memory(state_root, "sess_001")

    payload = build_agent_viewer_payload(state_root=state_root, session_id="sess_001")

    assert payload["available"] is True
    assert payload["summary"]["target_id"] == 3
    assert "核心特征：短发、黑色上衣。" in payload["modules"]["tracking"]["current_memory"]
    assert "摘要：" not in payload["modules"]["tracking"]["current_memory"]
    assert payload["modules"]["tracking"]["display_frame"]["frame_id"] == "frame_000001"
    assert payload["modules"]["tracking"]["display_frame"]["target_id"] == 3
    assert payload["modules"]["tracking"]["display_frame"]["image_data_url"].startswith("data:image/jpeg;base64,")
    assert payload["agent"]["conversation_history"][-1]["text"] == "目标在左侧。"
    assert payload["agent"]["conversation_history"][-1]["debug"]["behavior"] == "reply"
    assert payload["modules"]["tracking"]["memory_history"] == []
    assert payload["summary"]["status_kind"] == "tracking"
    assert payload["summary"]["status_label"] == "跟踪中"


def test_build_agent_viewer_payload_handles_missing_session(tmp_path: Path) -> None:
    payload = build_agent_viewer_payload(
        state_root=tmp_path / "state",
        session_id="missing_session",
    )

    assert payload["available"] is False
    assert payload["session_id"] == "missing_session"


def test_build_agent_viewer_payload_uses_active_session_when_session_id_is_omitted(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    store = LiveSessionStore(state_root)
    frame_path = _frame_image(tmp_path / "frame_active.jpg")
    _write_environment_frame(
        state_root=state_root,
        session_id="sess_active",
        frame_id="frame_000001",
        timestamp_ms=1710000000000,
        image_path=frame_path,
        detections=[{"track_id": 5, "bbox": [10, 20, 30, 40], "score": 0.95}],
    )
    store.ingest_robot_event(
        session_id="sess_active",
        device_id="robot_01",
        frame={
            "frame_id": "frame_000001",
            "timestamp_ms": 1710000000000,
            "image_path": str(frame_path),
        },
        detections=[{"track_id": 5, "bbox": [10, 20, 30, 40], "score": 0.95}],
        text="观察画面",
    )
    ActiveSessionStore(state_root).write("sess_active")

    payload = build_agent_viewer_payload(state_root=state_root)

    assert payload["available"] is True
    assert payload["session_id"] == "sess_active"
    assert payload["observation"]["latest_frame"]["frame_id"] == "frame_000001"


def test_build_agent_viewer_payload_hides_raw_perception_frames_before_target_confirmation(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    store = LiveSessionStore(state_root)
    frame_path = _frame_image(tmp_path / "frame_waiting.jpg")
    _write_environment_frame(
        state_root=state_root,
        session_id="sess_waiting",
        frame_id="frame_000001",
        timestamp_ms=1710000000000,
        image_path=frame_path,
        detections=[{"track_id": 5, "bbox": [10, 20, 30, 40], "score": 0.95}],
        text="开始跟踪穿黑衣服的人",
    )
    store.ingest_robot_event(
        session_id="sess_waiting",
        device_id="robot_01",
        frame={
            "frame_id": "frame_000001",
            "timestamp_ms": 1710000000000,
            "image_path": str(frame_path),
        },
        detections=[{"track_id": 5, "bbox": [10, 20, 30, 40], "score": 0.95}],
        text="开始跟踪穿黑衣服的人",
        request_id="req_001",
        request_function="chat",
    )

    payload = build_agent_viewer_payload(state_root=state_root, session_id="sess_waiting")

    assert payload["available"] is True
    assert payload["agent"]["latest_result"] is None
    assert payload["modules"]["tracking"]["display_frame"] is None
    assert payload["summary"]["frame_id"] == "frame_000001"
    assert payload["summary"]["detection_count"] == 1


def test_build_agent_viewer_payload_follows_latest_perception_frame_after_confirmation(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    store = LiveSessionStore(state_root)
    perception = LocalPerceptionService(state_root)
    frame_a = _frame_image(tmp_path / "frame_a.jpg")
    frame_b = _frame_image(tmp_path / "frame_b.jpg")
    perception.write_observation(
        RobotIngestEvent(
            session_id="sess_live",
            device_id="robot_01",
            frame=RobotFrame(
                frame_id="frame_000001",
                timestamp_ms=1710000000000,
                image_path=str(frame_a),
            ),
            detections=[RobotDetection(track_id=3, bbox=[10, 20, 30, 40], score=0.95)],
            text="先看看画面",
        ),
    )
    LocalSystem1Service(state_root).write_result(
        {
            "frame_id": "frame_000001",
            "timestamp_ms": 1710000000000,
            "image_path": str(frame_a),
            "detections": [{"track_id": 3, "bbox": [10, 20, 30, 40], "score": 0.95}],
        }
    )
    store.append_chat_request(
        session_id="sess_live",
        device_id="robot_01",
        text="先看看画面",
        request_id="req_001",
    )
    store.apply_agent_result(
        "sess_live",
        {
            "request_id": "req_001",
            "function": "tracking",
            "behavior": "init",
            "frame_id": "frame_000001",
            "target_id": 3,
            "text": "已确认目标。",
            "memory": _memory_payload(),
        },
    )
    perception.write_observation(
        RobotIngestEvent(
            session_id="sess_live",
            device_id="robot_01",
            frame=RobotFrame(
                frame_id="frame_000002",
                timestamp_ms=1710000001000,
                image_path=str(frame_b),
            ),
            detections=[RobotDetection(track_id=3, bbox=[12, 24, 34, 46], score=0.96)],
            text="更新画面",
        ),
    )
    LocalSystem1Service(state_root).write_result(
        {
            "frame_id": "frame_000002",
            "timestamp_ms": 1710000001000,
            "image_path": str(frame_b),
            "detections": [{"track_id": 3, "bbox": [12, 24, 34, 46], "score": 0.96}],
        }
    )
    AgentSessionStore(state_root).patch_skill_state(
        "sess_live",
        skill_name="tracking",
        patch={
            "latest_target_id": 3,
            "pending_question": "",
        },
    )
    _write_tracking_memory(state_root, "sess_live")

    payload = build_agent_viewer_payload(state_root=state_root, session_id="sess_live")

    assert payload["modules"]["tracking"]["display_frame"]["frame_id"] == "frame_000002"
    assert payload["modules"]["tracking"]["display_frame"]["bbox"] == [12, 24, 34, 46]
    assert payload["summary"]["frame_id"] == "frame_000002"


def test_build_agent_viewer_payload_marks_completed_stream(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    store = LiveSessionStore(state_root)
    perception = LocalPerceptionService(state_root)
    frame_path = _frame_image(tmp_path / "frame.jpg")
    perception.write_observation(
        RobotIngestEvent(
            session_id="sess_done",
            device_id="robot_01",
            frame=RobotFrame(
                frame_id="frame_000001",
                timestamp_ms=1710000000000,
                image_path=str(frame_path),
            ),
            detections=[RobotDetection(track_id=3, bbox=[10, 20, 30, 40], score=0.95)],
            text="更新画面",
        ),
    )
    perception.update_stream_status(status="completed", ended_at_ms=1710000001000)
    store.append_chat_request(
        session_id="sess_done",
        device_id="robot_01",
        text="继续跟踪",
        request_id="req_001",
    )
    store.apply_agent_result(
        "sess_done",
        {
            "request_id": "req_001",
            "function": "tracking",
            "behavior": "track",
            "frame_id": "frame_000001",
            "found": False,
            "decision": "wait",
            "text": "当前画面中未发现与历史目标特征一致的人，暂时无法继续绑定。",
        },
    )
    AgentSessionStore(state_root).patch_skill_state(
        "sess_done",
        skill_name="tracking",
        patch={
            "latest_target_id": 3,
            "pending_question": "",
        },
    )
    _write_tracking_memory(state_root, "sess_done")

    payload = build_agent_viewer_payload(state_root=state_root, session_id="sess_done")

    assert payload["summary"]["status_kind"] == "completed"
    assert payload["summary"]["status_label"] == "视频结束"
    assert payload["summary"]["stream_status"] == "completed"


def test_build_agent_viewer_payload_keeps_display_frame_during_wait(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    store = LiveSessionStore(state_root)
    frame_path = _frame_image(tmp_path / "frame_wait.jpg")
    _write_environment_frame(
        state_root=state_root,
        session_id="sess_wait_live",
        frame_id="frame_000010",
        timestamp_ms=1710000000000,
        image_path=frame_path,
        detections=[{"track_id": 8, "bbox": [11, 21, 31, 41], "score": 0.95}],
        text="更新画面",
    )
    store.ingest_robot_event(
        session_id="sess_wait_live",
        device_id="robot_01",
        frame={
            "frame_id": "frame_000010",
            "timestamp_ms": 1710000000000,
            "image_path": str(frame_path),
        },
        detections=[{"track_id": 8, "bbox": [11, 21, 31, 41], "score": 0.95}],
        text="更新画面",
        record_conversation=False,
    )
    store.append_chat_request(
        session_id="sess_wait_live",
        device_id="robot_01",
        text="继续跟踪",
        request_id="req_001",
    )
    store.apply_agent_result(
        "sess_wait_live",
        {
            "request_id": "req_001",
            "function": "tracking",
            "behavior": "track",
            "frame_id": "frame_000010",
            "target_id": None,
            "found": False,
            "decision": "wait",
            "text": "当前画面中未发现与历史目标特征一致的人，暂时无法继续绑定。",
        },
    )
    AgentSessionStore(state_root).patch_skill_state(
        "sess_wait_live",
        skill_name="tracking",
        patch={
            "latest_target_id": 8,
            "pending_question": "",
        },
    )
    _write_tracking_memory(state_root, "sess_wait_live")

    payload = build_agent_viewer_payload(state_root=state_root, session_id="sess_wait_live")

    assert payload["summary"]["status_kind"] == "seeking"
    assert payload["modules"]["tracking"]["display_frame"]["frame_id"] == "frame_000010"
    assert payload["modules"]["tracking"]["display_frame"]["target_id"] == 8
    assert payload["modules"]["tracking"]["display_frame"]["bbox"] == [11, 21, 31, 41]


def test_build_agent_viewer_payload_handles_missing_active_session(tmp_path: Path) -> None:
    payload = build_agent_viewer_payload(
        state_root=tmp_path / "state",
    )

    assert payload["available"] is False
    assert payload["session_id"] is None


def test_build_agent_viewer_payload_marks_wait_result_as_seeking(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    store = LiveSessionStore(state_root)
    frame_path = _frame_image(tmp_path / "frame_wait_result.jpg")
    _write_environment_frame(
        state_root=state_root,
        session_id="sess_wait",
        frame_id="frame_000001",
        timestamp_ms=1710000000000,
        image_path=frame_path,
        detections=[{"track_id": 5, "bbox": [10, 20, 30, 40], "score": 0.95}],
    )
    store.ingest_robot_event(
        session_id="sess_wait",
        device_id="robot_01",
        frame={
            "frame_id": "frame_000001",
            "timestamp_ms": 1710000000000,
            "image_path": str(frame_path),
        },
        detections=[{"track_id": 5, "bbox": [10, 20, 30, 40], "score": 0.95}],
        text="观察画面",
    )
    store.apply_agent_result(
        "sess_wait",
        {
            "behavior": "track",
            "frame_id": "frame_000001",
            "decision": "wait",
            "text": "当前证据不足。",
        },
    )
    AgentSessionStore(state_root).patch_skill_state(
        "sess_wait",
        skill_name="tracking",
        patch={
            "latest_target_id": 5,
            "pending_question": "",
        },
    )
    _write_tracking_memory(state_root, "sess_wait")

    payload = build_agent_viewer_payload(state_root=state_root, session_id="sess_wait")

    assert payload["summary"]["status_kind"] == "seeking"
    assert payload["summary"]["status_label"] == "寻找中"


def test_build_agent_viewer_payload_exposes_recent_conversation_window(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    store = LiveSessionStore(state_root)
    store.ingest_robot_event(
        session_id="sess_history",
        device_id="robot_01",
        frame={
            "frame_id": "frame_000001",
            "timestamp_ms": 1710000000000,
            "image_base64": _tiny_jpeg_base64(),
        },
        detections=[],
        text="初始化观察",
    )

    for index in range(12):
        request_id = f"req_{index:03d}"
        store.append_chat_request(
            session_id="sess_history",
            device_id="robot_01",
            text=f"user turn {index}",
            request_id=request_id,
        )
        store.apply_agent_result(
            "sess_history",
            {
                "request_id": request_id,
                "function": "chat",
                "behavior": "reply",
                "frame_id": "frame_000001",
                "text": f"assistant turn {index}",
            },
        )

    payload = build_agent_viewer_payload(state_root=state_root, session_id="sess_history")

    assert len(payload["agent"]["conversation_history"]) == 8
    assert payload["agent"]["conversation_history"][0]["text"] == "user turn 8"
    assert payload["agent"]["conversation_history"][-1]["text"] == "assistant turn 11"
    assert payload["agent"]["conversation_history"][-1]["debug"]["request_id"] == "req_011"
