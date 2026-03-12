from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from PIL import Image

from tracking_agent.core import PiAgentSessionLoop, SessionStore


def _write_fake_jpeg(path: Path) -> None:
    image = Image.new("RGB", (120, 120), color=(230, 230, 230))
    image.save(path, format="JPEG")


def _write_query_plan(tmp_path: Path) -> Path:
    frame_paths = []
    for index in range(4):
        frame_path = tmp_path / f"frame_{index}.jpg"
        _write_fake_jpeg(frame_path)
        frame_paths.append(frame_path)

    query_plan_path = tmp_path / "query_plan.json"
    query_plan_path.write_text(
        json.dumps(
            {
                "query_interval_seconds": 5,
                "recent_frame_count": 4,
                "batches": [
                    {
                        "batch_index": 0,
                        "query_time_seconds": 0.0,
                        "frames": [
                            {
                                "index": 0,
                                "timestamp_seconds": 0.0,
                                "path": str(frame_paths[0]),
                            }
                        ],
                    },
                    {
                        "batch_index": 1,
                        "query_time_seconds": 5.0,
                        "frames": [
                            {
                                "index": 0,
                                "timestamp_seconds": 0.0,
                                "path": str(frame_paths[0]),
                            },
                            {
                                "index": 1,
                                "timestamp_seconds": 1.0,
                                "path": str(frame_paths[1]),
                            },
                            {
                                "index": 2,
                                "timestamp_seconds": 2.0,
                                "path": str(frame_paths[2]),
                            },
                            {
                                "index": 3,
                                "timestamp_seconds": 3.0,
                                "path": str(frame_paths[3]),
                            },
                        ],
                    },
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return query_plan_path


class RecordingBackend:
    def __init__(self) -> None:
        self.bootstrap_calls = []
        self.init_calls = []
        self.locate_calls = []
        self.rewrite_calls = []
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
            "confidence": 0.91,
            "reason": "bootstrap target found",
            "autonomous_inference": None,
            "needs_clarification": False,
            "clarification_question": None,
        }

    def initialize_memory(self, frame_paths, target_crop_path, bootstrap_description=None):
        self.init_calls.append(
            {
                "frame_paths": [str(path) for path in frame_paths],
                "target_crop_path": str(target_crop_path),
                "bootstrap_description": bootstrap_description,
            }
        )
        return (
            "# Tracking Memory\n\n"
            "已经根据目标截图重新描述这个人，不再依赖初始自然语言描述。下一轮继续定位时，优先比较体型、发型、裤子和鞋子这些差异。\n"
        )

    def locate_target(
        self,
        memory_markdown: str,
        frame_paths,
        reference_frame_paths=None,
        human_guidance=None,
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
            "bbox": [11, 22, 33, 44],
            "confidence": 0.9,
            "reason": "matched target in the newest frame",
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
        return (
            "# Tracking Memory\n\n"
            "当前人物特征主要来自最近一次参考截图。下一轮优先检查左侧区域，并用体型、裤子和鞋子去和左边人群区分。\n"
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
        return "参考最近一次确认目标出现的整帧，这个人更可能还在左侧区域。"


class ClarifyingBackend(RecordingBackend):
    def __init__(self) -> None:
        super().__init__()
        self.should_clarify = True

    def locate_target(
        self,
        memory_markdown: str,
        frame_paths,
        reference_frame_paths=None,
        human_guidance=None,
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
        if self.should_clarify and not human_guidance:
            return {
                "found": False,
                "bbox": None,
                "confidence": 0.34,
                "reason": "multiple plausible candidates",
                "autonomous_inference": {
                    "likely_whereabouts": ["左侧通道"],
                    "likely_action": "继续向左",
                    "priority_search_regions": ["左侧门口"],
                },
                "needs_clarification": True,
                "clarification_question": "你指的是左边靠门口的人吗？",
            }
        self.should_clarify = False
        return {
            "found": True,
            "bbox": [1, 2, 3, 4],
            "confidence": 0.81,
            "reason": "clarification resolved ambiguity",
            "autonomous_inference": None,
            "needs_clarification": False,
            "clarification_question": None,
        }


def test_session_loop_treats_brief_first_message_as_initialization(tmp_path: Path) -> None:
    query_plan_path = _write_query_plan(tmp_path)
    backend = RecordingBackend()
    loop = PiAgentSessionLoop(
        session_id="demo",
        query_plan_path=query_plan_path,
        store=SessionStore(tmp_path / "sessions"),
        backend=backend,
    )

    result = loop.process_user_message("坐在凳子上的人")

    assert result["intent"] == "initialize_target"
    assert result["batch"]["batch_index"] == 0
    assert backend.bootstrap_calls[0]["target_description"] == "坐在凳子上的人"
    assert backend.init_calls[0]["bootstrap_description"] == "坐在凳子上的人"
    assert result["session"]["status"] == "initialized"
    assert result["session"]["latest_target_crop_path"]
    assert result["session"]["latest_confirmed_frame_path"]
    assert len(result["session"]["reference_crop_paths"]) == 1


def test_session_loop_advances_batches_for_continue_and_chat_uses_last_context(
    tmp_path: Path,
) -> None:
    query_plan_path = _write_query_plan(tmp_path)
    backend = RecordingBackend()
    loop = PiAgentSessionLoop(
        session_id="demo",
        query_plan_path=query_plan_path,
        store=SessionStore(tmp_path / "sessions"),
        backend=backend,
    )

    loop.process_user_message("帮我跟踪坐在凳子上的人")
    track_result = loop.process_user_message("继续")
    chat_result = loop.process_user_message("这个人去哪了")

    assert track_result["intent"] == "continue_tracking"
    assert track_result["batch"]["batch_index"] == 1
    assert backend.locate_calls[0]["frame_paths"][-1].endswith("frame_3.jpg")
    assert len(backend.locate_calls[0]["frame_paths"]) == 1
    assert backend.locate_calls[0]["reference_frame_paths"] == [str(tmp_path / "frame_0.jpg")]
    assert len(backend.rewrite_calls) == 1
    assert backend.rewrite_calls[0]["frame_paths"] == [str(tmp_path / "frame_3.jpg")]
    assert backend.rewrite_calls[0]["reference_frame_paths"] == [str(tmp_path / "frame_3.jpg")]
    assert chat_result["intent"] == "ask_whereabouts"
    assert backend.chat_calls[0]["frame_paths"][-1].endswith("frame_3.jpg")
    assert backend.chat_calls[0]["reference_frame_paths"] == [str(tmp_path / "frame_3.jpg")]
    assert chat_result["answer"].endswith("更可能还在左侧区域。")


def test_session_loop_reruns_same_batch_after_clarification(tmp_path: Path) -> None:
    query_plan_path = _write_query_plan(tmp_path)
    backend = ClarifyingBackend()
    loop = PiAgentSessionLoop(
        session_id="demo",
        query_plan_path=query_plan_path,
        store=SessionStore(tmp_path / "sessions"),
        backend=backend,
    )

    loop.process_user_message("跟踪穿深色衣服的人")
    first_track = loop.process_user_message("继续")
    clarified = loop.process_user_message("我指的是左边靠门口、刚刚转身的那个人")

    assert first_track["session"]["status"] == "clarifying"
    assert clarified["intent"] == "clarify_target"
    assert clarified["locate_result"]["found"] is True
    assert backend.locate_calls[0]["frame_paths"] == backend.locate_calls[1]["frame_paths"]
    assert len(backend.locate_calls[0]["frame_paths"]) == 1
    assert backend.locate_calls[0]["reference_frame_paths"] == [str(tmp_path / "frame_0.jpg")]
    assert len(backend.rewrite_calls) == 1
    assert backend.rewrite_calls[0]["frame_paths"] == [str(tmp_path / "frame_3.jpg")]
    assert backend.rewrite_calls[0]["reference_frame_paths"] == [str(tmp_path / "frame_3.jpg")]
    runtime_state = loop.get_runtime_state()
    assert runtime_state["next_batch_index"] == 2
    assert runtime_state["last_batch_index"] == 1


def test_session_loop_uses_history_frames_only_for_missing_recovery(tmp_path: Path) -> None:
    query_plan_path = _write_query_plan(tmp_path)

    class MissingRecoveryBackend(RecordingBackend):
        def __init__(self) -> None:
            super().__init__()
            self.first_call = True

        def locate_target(
            self,
            memory_markdown: str,
            frame_paths,
            reference_frame_paths=None,
            human_guidance=None,
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
            if self.first_call:
                self.first_call = False
                return {
                    "found": False,
                    "bbox": None,
                    "confidence": 0.2,
                    "reason": "latest frame missing target",
                    "autonomous_inference": {
                        "likely_whereabouts": ["左侧转角"],
                        "likely_action": "继续向左",
                        "priority_search_regions": ["左侧门口"],
                    },
                    "needs_clarification": False,
                    "clarification_question": None,
                }
            return {
                "found": True,
                "bbox": [1, 2, 3, 4],
                "confidence": 0.8,
                "reason": "recovered with history",
                "autonomous_inference": None,
                "needs_clarification": False,
                "clarification_question": None,
            }

    backend = MissingRecoveryBackend()
    loop = PiAgentSessionLoop(
        session_id="demo",
        query_plan_path=query_plan_path,
        store=SessionStore(tmp_path / "sessions"),
        backend=backend,
    )

    loop.process_user_message("跟踪穿深色衣服的人")
    result = loop.process_user_message("继续")

    assert result["locate_result"]["found"] is True
    assert len(backend.locate_calls) == 2
    assert len(backend.locate_calls[0]["frame_paths"]) == 1
    assert len(backend.locate_calls[1]["frame_paths"]) == 4
    assert backend.locate_calls[0]["reference_frame_paths"] == [str(tmp_path / "frame_0.jpg")]
    assert backend.locate_calls[1]["reference_frame_paths"] == [str(tmp_path / "frame_0.jpg")]
    assert len(backend.rewrite_calls) == 1
    assert len(backend.rewrite_calls[0]["frame_paths"]) == 4


def test_cli_loop_dry_run_processes_messages(tmp_path: Path) -> None:
    query_plan_path = _write_query_plan(tmp_path)
    sessions_root = tmp_path / "sessions"

    result = subprocess.run(
        [
            sys.executable,
            "scaffold/cli/run_session.py",
            "--query-plan",
            str(query_plan_path),
            "--sessions-root",
            str(sessions_root),
            "--session-id",
            "demo",
            "--dry-run",
            "--show-memory",
            "--message",
            "坐在凳子上的人",
            "--message",
            "继续",
            "--message",
            "这个人去哪了",
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
    )

    lines = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 3
    assert lines[0]["intent"] == "initialize_target"
    assert lines[1]["intent"] == "continue_tracking"
    assert lines[2]["intent"] == "ask_whereabouts"
    assert "memory_text" in lines[0]
    assert "目标裁剪图" in lines[0]["memory_text"]
    assert "memory_markdown" in lines[2]
