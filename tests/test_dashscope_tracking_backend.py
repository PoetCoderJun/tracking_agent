from __future__ import annotations

from pathlib import Path

from PIL import Image

from tracking_agent.dashscope_tracking_backend import DashScopeTrackingBackend


def _write_fake_jpeg(path: Path) -> None:
    path.write_bytes(b"\xff\xd8\xff\xe0" + b"fake-jpeg-data")


def _write_real_jpeg(path: Path, size=(100, 50)) -> None:
    Image.new("RGB", size, color="white").save(path, format="JPEG")


class FakeVisionClient:
    def __init__(self, text_response: str, json_response):
        self.text_response = text_response
        self.json_response = json_response
        self.calls = []

    def complete_text(
        self,
        instruction,
        frame_paths,
        output_contract,
        temperature=0,
        max_tokens=700,
        model=None,
    ):
        self.calls.append(
            {
                "mode": "text",
                "instruction": instruction,
                "frame_paths": [str(path) for path in frame_paths],
                "output_contract": output_contract,
                "model": model,
                "max_tokens": max_tokens,
            }
        )
        return self.text_response

    def complete_json(
        self,
        instruction,
        frame_paths,
        output_contract,
        parser,
        temperature=0,
        max_tokens=500,
        model=None,
    ):
        self.calls.append(
            {
                "mode": "json",
                "instruction": instruction,
                "frame_paths": [str(path) for path in frame_paths],
                "output_contract": output_contract,
                "model": model,
                "max_tokens": max_tokens,
            }
        )
        return parser(self.json_response)


def test_dashscope_tracking_backend_initializes_memory_with_fixed_sections(
    tmp_path: Path,
) -> None:
    frame_path = tmp_path / "frame.jpg"
    crop_path = tmp_path / "crop.jpg"
    _write_fake_jpeg(frame_path)
    _write_fake_jpeg(crop_path)

    backend = DashScopeTrackingBackend(
        client=FakeVisionClient(
            text_response="目标是坐在凳子上的人，位于画面左侧。",
            json_response={},
        )
    )

    memory = backend.initialize_memory(
        frame_paths=[frame_path],
        target_crop_path=crop_path,
        bootstrap_description="坐在凳子上的人",
    )

    assert memory.startswith("# Tracking Memory")
    assert backend._client.calls[0]["frame_paths"][0].endswith("crop.jpg")
    assert "直接输出一段话，不要分 section，不要列点" in backend._client.calls[0]["instruction"]
    assert "后半段直接给出怎么和周围环境里的人区分开的建议" in backend._client.calls[0]["instruction"]
    assert "不要把场景位置、Main Agent、Sub-agent、模型、bbox、确认、匹配写进 memory" in backend._client.calls[0]["instruction"]
    assert "不要分 section" in backend._client.calls[0]["output_contract"]
    assert backend._client.calls[0]["max_tokens"] == 180


def test_dashscope_tracking_backend_bootstrap_target_uses_initial_description(
    tmp_path: Path,
) -> None:
    frame_path = tmp_path / "frame.jpg"
    _write_real_jpeg(frame_path, size=(100, 50))

    backend = DashScopeTrackingBackend(
        client=FakeVisionClient(
            text_response="unused",
            json_response={
                "found": True,
                "bbox": [100, 200, 900, 800],
                "confidence": 0.91,
                "reason": "matched initial user description",
                "autonomous_inference": None,
                "needs_clarification": False,
                "clarification_question": None,
            },
        )
    )

    result = backend.bootstrap_target(
        target_description="坐在凳子上的人",
        frame_paths=[frame_path],
    )

    assert result["bbox"] == [10, 10, 90, 40]
    assert backend._client.calls[0]["mode"] == "json"
    assert "初始描述" in backend._client.calls[0]["instruction"]
    assert "紧贴目标人体可见区域的框" in backend._client.calls[0]["instruction"]


def test_dashscope_tracking_backend_supports_smaller_subagent_model(tmp_path: Path) -> None:
    frame_path = tmp_path / "frame.jpg"
    crop_path = tmp_path / "crop.jpg"
    _write_real_jpeg(frame_path, size=(100, 50))
    _write_real_jpeg(crop_path, size=(40, 40))

    client = FakeVisionClient(
        text_response="目标在商场中庭附近活动。",
        json_response={
            "found": True,
            "bbox": [1, 2, 3, 4],
            "confidence": 0.9,
            "reason": "matched",
            "autonomous_inference": None,
            "needs_clarification": False,
            "clarification_question": None,
        },
    )
    backend = DashScopeTrackingBackend(
        client=client,
        main_model="qwen-vl-max",
        sub_model="qwen-vl-plus",
    )

    backend.bootstrap_target("坐在凳子上的人", [frame_path])
    backend.initialize_memory([frame_path], crop_path, bootstrap_description="坐在凳子上的人")

    assert client.calls[0]["model"] == "qwen-vl-max"
    assert client.calls[1]["model"] == "qwen-vl-plus"


def test_dashscope_tracking_backend_validates_locate_result(tmp_path: Path) -> None:
    frame_path = tmp_path / "frame.jpg"
    _write_real_jpeg(frame_path, size=(200, 100))

    backend = DashScopeTrackingBackend(
        client=FakeVisionClient(
            text_response="unused",
            json_response={
                "found": False,
                "bbox": None,
                "confidence": 0.34,
                "reason": "multiple candidates remain",
                "autonomous_inference": {
                    "likely_whereabouts": ["左侧转角附近"],
                    "likely_action": "继续朝左侧移动",
                    "priority_search_regions": ["左侧门口"],
                },
                "needs_clarification": True,
                "clarification_question": "你指的是左边还是中间的人？",
            },
        )
    )

    result = backend.locate_target(
        memory_markdown="# Tracking Memory\n",
        frame_paths=[frame_path],
        reference_frame_paths=[frame_path],
        human_guidance="用户补充：目标更靠左。",
    )

    assert result["found"] is False
    assert result["needs_clarification"] is True
    assert "左边还是中间" in result["clarification_question"]
    assert backend._client.calls[0]["frame_paths"][0].endswith("frame.jpg")
    assert len(backend._client.calls[0]["frame_paths"]) == 2
    assert "第一张图片里的人就是目标人物" in backend._client.calls[0]["instruction"]
    assert "不要依赖场景位置，也不要依赖相对运动" in backend._client.calls[0]["instruction"]
    assert "没有把握就返回 found=false" in backend._client.calls[0]["instruction"]
    assert "存在一个明显最佳候选" not in backend._client.calls[0]["instruction"]
    assert backend._client.calls[0]["max_tokens"] == 220


def test_dashscope_tracking_backend_denormalizes_bbox_to_pixels(tmp_path: Path) -> None:
    frame_path = tmp_path / "frame.jpg"
    _write_real_jpeg(frame_path, size=(960, 400))

    backend = DashScopeTrackingBackend(
        client=FakeVisionClient(
            text_response="unused",
            json_response={
                "found": True,
                "bbox": [452, 448, 563, 853],
                "confidence": 0.95,
                "reason": "matched",
                "autonomous_inference": None,
                "needs_clarification": False,
                "clarification_question": None,
            },
        )
    )

    result = backend.locate_target(
        memory_markdown="# Tracking Memory\n",
        frame_paths=[frame_path],
        reference_frame_paths=[frame_path],
    )

    assert result["bbox"] == [434, 179, 540, 341]


def test_dashscope_tracking_backend_clamps_out_of_range_normalized_bbox(tmp_path: Path) -> None:
    frame_path = tmp_path / "frame.jpg"
    _write_real_jpeg(frame_path, size=(960, 400))

    backend = DashScopeTrackingBackend(
        client=FakeVisionClient(
            text_response="unused",
            json_response={
                "found": True,
                "bbox": [1130, 480, 1170, 830],
                "confidence": 0.8,
                "reason": "matched",
                "autonomous_inference": None,
                "needs_clarification": False,
                "clarification_question": None,
            },
        )
    )

    result = backend.locate_target(
        memory_markdown="# Tracking Memory\n",
        frame_paths=[frame_path],
        reference_frame_paths=[frame_path],
    )

    assert result["bbox"] == [959, 192, 960, 332]


def test_dashscope_tracking_backend_answers_chat(tmp_path: Path) -> None:
    frame_path = tmp_path / "frame.jpg"
    _write_fake_jpeg(frame_path)

    backend = DashScopeTrackingBackend(
        client=FakeVisionClient(
            text_response="目标更可能沿着左侧通道继续向前移动。",
            json_response={},
        )
    )

    answer = backend.answer_chat(
        memory_markdown="# Tracking Memory\n",
        question="这个人去哪了？",
        frame_paths=[frame_path],
        reference_frame_paths=[frame_path],
    )

    assert "左侧通道" in answer
    assert "回答保持简短" in backend._client.calls[0]["instruction"]
    assert backend._client.calls[0]["max_tokens"] == 160


def test_dashscope_tracking_backend_rewrite_memory_forbids_scene_position_in_traits(
    tmp_path: Path,
) -> None:
    frame_path = tmp_path / "frame.jpg"
    crop_path = tmp_path / "crop.jpg"
    _write_fake_jpeg(frame_path)
    _write_fake_jpeg(crop_path)

    client = FakeVisionClient(
        text_response="# Tracking Memory\n\n短发男性，戴眼镜，穿浅色上衣。和右侧更高、穿深色裤子的人区分时，优先看眼镜、体型和上衣亮度。\n",
        json_response={},
    )
    backend = DashScopeTrackingBackend(client=client)

    backend.rewrite_memory(
        previous_memory="# Tracking Memory\n",
        locate_result={
            "found": False,
            "bbox": None,
            "confidence": 0.0,
            "reason": "Main Agent 框选位置与预期轨迹一致",
            "autonomous_inference": None,
            "needs_clarification": False,
            "clarification_question": None,
        },
        frame_paths=[frame_path],
        reference_frame_paths=[crop_path],
    )

    assert "第一张图片里的人就是目标人物" in client.calls[0]["instruction"]
    assert "不要写 Main Agent、Sub-agent、模型、bbox、框选、确认、匹配、命中、记忆库这类词" in client.calls[0]["instruction"]
    assert "当前定位摘要" in client.calls[0]["instruction"]
    assert "Main Agent 结果" not in client.calls[0]["instruction"]
    assert "框选位置与预期轨迹一致" not in client.calls[0]["instruction"]
    assert "不要分 section" in client.calls[0]["output_contract"]
    assert client.calls[0]["max_tokens"] == 180
