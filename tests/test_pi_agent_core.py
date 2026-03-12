from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from tracking_agent.core import PiAgentCore, SessionStore, classify_user_intent
from tracking_agent.memory_format import normalize_memory_markdown


def _write_fake_jpeg(path: Path) -> None:
    image = Image.new("RGB", (120, 120), color=(240, 240, 240))
    image.save(path, format="JPEG")


class FakeTrackingBackend:
    def __init__(self) -> None:
        self.bootstrap_calls = []
        self.locate_calls = []
        self.rewrite_calls = []
        self.initialize_calls = []
        self.chat_calls = []

    def bootstrap_target(self, target_description: str, frame_paths):
        self.bootstrap_calls.append(
            {
                "target_description": target_description,
                "frame_paths": [str(path) for path in frame_paths],
            }
        )
        return {
            "found": True,
            "bbox": [10, 20, 60, 80],
            "confidence": 0.96,
            "reason": f"bootstrap matched {target_description}",
            "autonomous_inference": None,
            "needs_clarification": False,
            "clarification_question": None,
        }

    def initialize_memory(self, frame_paths, target_crop_path, bootstrap_description=None):
        self.initialize_calls.append(
            {
                "frame_paths": [str(path) for path in frame_paths],
                "target_crop_path": str(target_crop_path),
                "bootstrap_description": bootstrap_description,
            }
        )
        return normalize_memory_markdown(
            "初始化后已改为基于目标截图描述该人物，并优先用体型、发型、裤子、鞋子这些点和周围人区分。"
        )

    def locate_target(
        self,
        memory_markdown: str,
        frame_paths,
        reference_frame_paths=None,
        human_guidance: str | None = None,
        edge_hint=None,
    ):
        self.locate_calls.append(
            {
                "frame_paths": [str(path) for path in frame_paths],
                "reference_frame_paths": (
                    [str(path) for path in reference_frame_paths]
                    if reference_frame_paths
                    else []
                ),
                "human_guidance": human_guidance,
            }
        )
        return {
            "found": True,
            "bbox": [10, 20, 30, 40],
            "confidence": 0.92,
            "reason": "matched target by crop reference",
            "autonomous_inference": None,
            "needs_clarification": False,
            "clarification_question": None,
        }

    def rewrite_memory(
        self,
        previous_memory: str,
        locate_result,
        frame_paths,
        reference_frame_paths=None,
    ):
        self.rewrite_calls.append(
            {
                "frame_paths": [str(path) for path in frame_paths],
                "reference_frame_paths": (
                    [str(path) for path in reference_frame_paths]
                    if reference_frame_paths
                    else []
                ),
                "locate_result": locate_result,
            }
        )
        return normalize_memory_markdown(
            "仍然跟踪最近一次参考截图对应的同一个人。和右侧浅色上衣干扰人区分时，优先看体型、裤子和鞋子。"
        )

    def answer_chat(
        self,
        memory_markdown: str,
        question: str,
        frame_paths,
        reference_frame_paths=None,
    ):
        self.chat_calls.append(
            {
                "question": question,
                "frame_paths": [str(path) for path in frame_paths],
                "reference_frame_paths": (
                    [str(path) for path in reference_frame_paths]
                    if reference_frame_paths
                    else []
                ),
            }
        )
        return "基于当前记忆和最近一次确认目标出现的整帧，这个人更可能继续向左前方移动。"


class ClarifyBackend(FakeTrackingBackend):
    def locate_target(
        self,
        memory_markdown: str,
        frame_paths,
        reference_frame_paths=None,
        human_guidance: str | None = None,
        edge_hint=None,
    ):
        self.locate_calls.append(
            {
                "frame_paths": [str(path) for path in frame_paths],
                "reference_frame_paths": (
                    [str(path) for path in reference_frame_paths]
                    if reference_frame_paths
                    else []
                ),
                "human_guidance": human_guidance,
            }
        )
        return {
            "found": False,
            "bbox": None,
            "confidence": 0.36,
            "reason": "two candidates remain plausible",
            "autonomous_inference": {
                "likely_whereabouts": ["可能在左侧靠门区域附近"],
                "likely_action": "继续向左侧移动",
                "priority_search_regions": ["左侧门口", "左侧转角"],
            },
            "needs_clarification": True,
            "clarification_question": "你指的是靠左门口的人，还是靠中间的人？",
        }


class MissingThenRecoveredBackend(FakeTrackingBackend):
    def locate_target(
        self,
        memory_markdown: str,
        frame_paths,
        reference_frame_paths=None,
        human_guidance: str | None = None,
        edge_hint=None,
    ):
        self.locate_calls.append(
            {
                "frame_paths": [str(path) for path in frame_paths],
                "reference_frame_paths": (
                    [str(path) for path in reference_frame_paths]
                    if reference_frame_paths
                    else []
                ),
                "human_guidance": human_guidance,
            }
        )
        if len(frame_paths) == 1:
            return {
                "found": False,
                "bbox": None,
                "confidence": 0.21,
                "reason": "latest frame alone is insufficient",
                "autonomous_inference": {
                    "likely_whereabouts": ["左侧转角"],
                    "likely_action": "继续向左移动",
                    "priority_search_regions": ["左侧门口"],
                },
                "needs_clarification": False,
                "clarification_question": None,
            }
        return {
            "found": True,
            "bbox": [5, 6, 7, 8],
            "confidence": 0.77,
            "reason": "recovered with history frames",
            "autonomous_inference": None,
            "needs_clarification": False,
            "clarification_question": None,
        }


def test_pi_agent_core_initializes_tracks_and_answers_chat(tmp_path: Path) -> None:
    frame_paths = [tmp_path / "frame_000000.jpg", tmp_path / "frame_000001.jpg"]
    for path in frame_paths:
        _write_fake_jpeg(path)

    store = SessionStore(tmp_path / "sessions")
    core = PiAgentCore(store=store, backend=FakeTrackingBackend())

    init_result = core.initialize_target(
        session_id="demo",
        target_description="坐在凳子上的人",
        frame_paths=[frame_paths[0]],
    )
    assert init_result["session"]["status"] == "initialized"
    assert Path(init_result["session"]["memory_path"]).exists()
    assert init_result["bootstrap_result"]["bbox"] == [10, 20, 60, 80]
    assert Path(init_result["session"]["latest_target_crop_path"]).exists()
    assert init_result["session"]["latest_confirmed_frame_path"] == str(frame_paths[0])
    assert len(init_result["session"]["reference_crop_paths"]) == 1
    assert Path(init_result["frame_visualization_path"]).exists()
    assert core._backend.initialize_calls[0]["bootstrap_description"] == "坐在凳子上的人"

    track_result = core.run_tracking_step(
        session_id="demo",
        frame_paths=[frame_paths[-1]],
        recovery_frame_paths=frame_paths,
    )
    assert track_result["session"]["status"] == "tracked"
    assert track_result["locate_result"]["bbox"] == [10, 20, 30, 40]
    assert len(core._backend.locate_calls) == 1
    assert core._backend.locate_calls[0]["frame_paths"] == [str(frame_paths[-1])]
    assert core._backend.locate_calls[0]["reference_frame_paths"] == [str(frame_paths[0])]
    assert track_result["memory_updated"] is True
    assert track_result["crop_updated"] is True
    assert Path(track_result["frame_visualization_path"]).exists()

    memory_text = store.read_memory("demo")
    assert "仍然跟踪最近一次参考截图对应的同一个人" in memory_text
    assert len(core._backend.rewrite_calls) == 1
    assert core._backend.rewrite_calls[0]["frame_paths"] == [str(frame_paths[-1])]
    assert core._backend.rewrite_calls[0]["reference_frame_paths"] == [str(frame_paths[-1])]

    chat_result = core.answer_chat(
        session_id="demo",
        question="这个人去哪了？",
        frame_paths=[frame_paths[-1]],
    )
    assert "最近一次确认目标出现的整帧" in chat_result["answer"]
    assert core._backend.chat_calls[0]["reference_frame_paths"] == [str(frame_paths[-1])]

    state_payload = json.loads((tmp_path / "sessions" / "demo" / "session.json").read_text(encoding="utf-8"))
    assert state_payload["status"] == "tracked"
    assert state_payload["latest_result_path"]
    assert state_payload["latest_target_crop_path"]
    assert state_payload["latest_confirmed_frame_path"] == str(frame_paths[-1])
    assert len(state_payload["reference_crop_paths"]) == 2


def test_pi_agent_core_records_clarification_requests_and_notes(tmp_path: Path) -> None:
    frame_paths = [tmp_path / f"frame_{index:06d}.jpg" for index in range(3)]
    for path in frame_paths:
        _write_fake_jpeg(path)

    store = SessionStore(tmp_path / "sessions")
    core = PiAgentCore(store=store, backend=ClarifyBackend())
    core.initialize_target(
        session_id="demo",
        target_description="穿深色衣服的人",
        frame_paths=[frame_paths[0]],
    )

    track_result = core.run_tracking_step(
        session_id="demo",
        frame_paths=[frame_paths[-1]],
        recovery_frame_paths=frame_paths,
    )
    assert track_result["session"]["status"] == "clarifying"
    assert track_result["locate_result"]["needs_clarification"] is True
    assert "靠左门口的人" in track_result["session"]["pending_clarification_question"]
    assert track_result["memory_updated"] is False
    assert core._backend.rewrite_calls == []

    clarified = core.add_clarification(
        session_id="demo",
        note="我指的是靠左门口、刚刚转身的那个人",
    )
    assert clarified["session"]["clarification_notes"] == [
        "我指的是靠左门口、刚刚转身的那个人"
    ]


def test_pi_agent_core_uses_recovery_frames_only_when_missing(tmp_path: Path) -> None:
    frame_paths = [tmp_path / f"frame_{index:06d}.jpg" for index in range(4)]
    for path in frame_paths:
        _write_fake_jpeg(path)

    backend = MissingThenRecoveredBackend()
    store = SessionStore(tmp_path / "sessions")
    core = PiAgentCore(store=store, backend=backend)
    core.initialize_target(
        session_id="demo",
        target_description="穿深色衣服的人",
        frame_paths=[frame_paths[0]],
    )

    track_result = core.run_tracking_step(
        session_id="demo",
        frame_paths=[frame_paths[-1]],
        recovery_frame_paths=frame_paths,
    )

    assert len(backend.locate_calls) == 2
    assert backend.locate_calls[0]["frame_paths"] == [str(frame_paths[-1])]
    assert backend.locate_calls[1]["frame_paths"] == [str(path) for path in frame_paths]
    assert backend.locate_calls[0]["reference_frame_paths"] == [str(frame_paths[0])]
    assert backend.locate_calls[1]["reference_frame_paths"] == [str(frame_paths[0])]
    assert track_result["locate_result"]["bbox"] == [5, 6, 7, 8]
    assert track_result["memory_updated"] is True
    assert track_result["crop_updated"] is True
    assert len(backend.rewrite_calls) == 1
    assert backend.rewrite_calls[0]["frame_paths"] == [str(path) for path in frame_paths]
    assert backend.rewrite_calls[0]["reference_frame_paths"] == [str(frame_paths[-1])]


def test_classify_user_intent_covers_tracking_dialogue() -> None:
    assert classify_user_intent("帮我跟踪坐在凳子上的人", has_active_session=False) == "initialize_target"
    assert classify_user_intent("换一个目标，跟踪左边的人", has_active_session=True) == "replace_target"
    assert classify_user_intent("这个人去哪了", has_active_session=True) == "ask_whereabouts"
    assert classify_user_intent("我指的是左边更高的那个人", has_active_session=True) == "clarify_target"
