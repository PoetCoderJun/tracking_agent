from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from PIL import Image

from tracking_agent.dashscope_client import DashScopeVisionClient, parse_bbox_response_content
from tracking_agent.memory_format import normalize_memory_markdown
from tracking_agent.output_validator import (
    denormalize_bbox_from_1000_scale,
    validate_locate_result,
)


class DashScopeTrackingBackend:
    def __init__(
        self,
        client: DashScopeVisionClient,
        main_model: Optional[str] = None,
        sub_model: Optional[str] = None,
    ):
        self._client = client
        self._main_model = main_model
        self._sub_model = sub_model or main_model

    def _latest_frame_size(self, frame_paths: Sequence[Path]) -> tuple[int, int]:
        if not frame_paths:
            raise ValueError("frame_paths must not be empty")
        with Image.open(frame_paths[-1]) as image:
            return image.size

    def _compact_locate_result(self, locate_result: Dict[str, Any]) -> Dict[str, Any]:
        summary = {
            "found": locate_result.get("found", False),
            "bbox": locate_result.get("bbox"),
            "confidence": locate_result.get("confidence", 0.0),
            "needs_clarification": locate_result.get("needs_clarification", False),
            "clarification_question": locate_result.get("clarification_question"),
        }
        if not summary["found"]:
            summary["autonomous_inference"] = locate_result.get("autonomous_inference")
        return summary

    def bootstrap_target(
        self,
        target_description: str,
        frame_paths: Sequence[Path],
    ) -> Dict[str, Any]:
        instruction = (
            "你现在负责根据用户的一句初始描述，在当前图像中找到这个人。"
            f'这句初始描述是：“{target_description}”。'
            "这句描述只用于这一次初始化定位。"
            "请在最新一帧中找出目标的 bbox。"
            "请返回紧贴目标人体可见区域的框，不要把旁边的人或大块背景包进去。"
            "如果存在多个合理候选，请不要猜测，直接返回 needs_clarification=true 并提出一个聚焦的澄清问题。"
        )
        output_contract = (
            "只返回合法 JSON，格式为："
            '{"found": true|false, "bbox": [x1, y1, x2, y2] | null, '
            '"confidence": 0.0, "reason": "简短解释", '
            '"autonomous_inference": {"likely_whereabouts": ["..."], "likely_action": "...", '
            '"priority_search_regions": ["..."]} | null, '
            '"needs_clarification": true|false, '
            '"clarification_question": "问题或 null"}。'
        )

        def _parser(content: str) -> Dict[str, Any]:
            parsed = parse_bbox_response_content(content)
            if parsed.get("bbox") is not None:
                parsed["bbox"] = denormalize_bbox_from_1000_scale(
                    parsed["bbox"],
                    image_size=self._latest_frame_size(frame_paths),
                )
            parsed["autonomous_inference"] = parsed.get("autonomous_inference")
            parsed["needs_clarification"] = parsed.get("needs_clarification", False)
            parsed["clarification_question"] = parsed.get("clarification_question")
            return validate_locate_result(parsed)

        return self._client.complete_json(
            instruction=instruction,
            frame_paths=frame_paths,
            output_contract=output_contract,
            parser=_parser,
            temperature=0,
            max_tokens=500,
            model=self._main_model,
        )

    def initialize_memory(
        self,
        frame_paths: Sequence[Path],
        target_crop_path: Path,
        bootstrap_description: Optional[str] = None,
    ) -> str:
        instruction = (
            "请根据第一张目标裁剪图和后面的场景帧，初始化一份极短的 tracking memory，供下一轮定位使用。"
            "忽略用户最初描述，只看当前图像。"
            "直接输出一段话，不要分 section，不要列点。"
            "前半段尽可能从任何角度详细描述这个人的特征，优先写体型、发型、裤子、鞋子、眼镜、背包、稳定配饰，也可以补充衣着版型和颜色细节。"
            "后半段直接给出怎么和周围环境里的人区分开的建议。"
            "不要把场景位置、Main Agent、Sub-agent、模型、bbox、确认、匹配写进 memory。"
            "如果不确定，用“疑似”或“可能”。"
            "整体保持一小段话，越短越好。"
        )
        output_contract = (
            "只返回 Markdown 正文，不要分 section，不要返回 JSON，不要使用 ``` 代码块围栏。尽量短。"
        )
        memory = self._client.complete_text(
            instruction=instruction,
            frame_paths=[target_crop_path, *frame_paths],
            output_contract=output_contract,
            temperature=0,
            max_tokens=180,
            model=self._sub_model,
        )
        return normalize_memory_markdown(memory)

    def locate_target(
        self,
        memory_markdown: str,
        frame_paths: Sequence[Path],
        reference_frame_paths: Optional[Sequence[Path]] = None,
        human_guidance: Optional[str] = None,
        edge_hint: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        memory_markdown = normalize_memory_markdown(memory_markdown)
        guidance_block = f"\n人工澄清信息：\n{human_guidance}" if human_guidance else ""
        edge_block = (
            f"\n端侧提示：\n{json.dumps(edge_hint, ensure_ascii=True)}"
            if edge_hint
            else ""
        )
        reference_block = (
            "第一张图片里的人就是目标人物。"
            "后面的图片是当前需要搜索的场景，最后一张是要输出 bbox 的帧。"
            if reference_frame_paths
            else "输入图片按时间从旧到新排列，最后一张是要输出 bbox 的帧。"
        )
        instruction = (
            f"{reference_block}"
            "请参照目标人物和下面这份简短 tracking memory，在最后一张图中找到同一个人并给出 bounding box。"
            "只判断最后一张图。"
            "优先看人物自身较稳定的外观特征：体型、发型、裤子、鞋子、眼镜、背包、稳定配饰。"
            "不要依赖用户最初描述，不要依赖场景位置，也不要依赖相对运动。"
            "bbox 必须紧贴人体可见区域，不要包含旁人或大块背景。"
            "没有把握就返回 found=false。"
            "如果有多个相近候选，返回 needs_clarification=true。"
            "tracking memory 只作辅助，不是绝对真值。\n\n"
            f"当前 tracking memory：\n{memory_markdown}"
            f"{guidance_block}"
            f"{edge_block}\n\n"
            "若 found=false，请提供简短 autonomous_inference。"
            "若 needs_clarification=true，请只提一个聚焦问题。"
        )
        output_contract = (
            "只返回合法 JSON，格式为："
            '{"found": true|false, "bbox": [x1, y1, x2, y2] | null, '
            '"confidence": 0.0, "reason": "简短解释", '
            '"autonomous_inference": {"likely_whereabouts": ["..."], "likely_action": "...", '
            '"priority_search_regions": ["..."]} | null, '
            '"needs_clarification": true|false, '
            '"clarification_question": "问题或 null"}。'
        )

        def _parser(content: str) -> Dict[str, Any]:
            parsed = parse_bbox_response_content(content)
            if parsed.get("bbox") is not None:
                parsed["bbox"] = denormalize_bbox_from_1000_scale(
                    parsed["bbox"],
                    image_size=self._latest_frame_size(frame_paths),
                )
            parsed["autonomous_inference"] = parsed.get("autonomous_inference")
            parsed["needs_clarification"] = parsed.get("needs_clarification", False)
            parsed["clarification_question"] = parsed.get("clarification_question")
            return validate_locate_result(parsed)

        request_frames = [*(reference_frame_paths or []), *frame_paths]
        return self._client.complete_json(
            instruction=instruction,
            frame_paths=request_frames,
            output_contract=output_contract,
            parser=_parser,
            temperature=0,
            max_tokens=220,
            model=self._main_model,
        )

    def rewrite_memory(
        self,
        previous_memory: str,
        locate_result: Dict[str, Any],
        frame_paths: Sequence[Path],
        reference_frame_paths: Optional[Sequence[Path]] = None,
    ) -> str:
        previous_memory = normalize_memory_markdown(previous_memory)
        reference_block = (
            "第一张图片里的人就是目标人物。"
            "后面的图片是当前场景帧。"
            if reference_frame_paths
            else "输入图片是当前的场景帧。"
        )
        instruction = (
            f"{reference_block}"
            "请根据目标人物、当前图像和下面的定位摘要，直接重写 tracking memory，供下一轮定位使用。"
            "忽略用户最初描述。"
            "不要复述上一版 memory。"
            "不要写 Main Agent、Sub-agent、模型、bbox、框选、确认、匹配、命中、记忆库这类词。"
            "直接输出一段话，不要分 section，不要列点。"
            "前半段尽可能从任何角度详细描述这个人的特征，优先写体型、发型、裤子、鞋子、眼镜、背包、稳定配饰，也可以补充衣着版型和颜色细节。"
            "不要把位置、动作或场景写成主体描述。"
            "后半段直接给出怎么和周围环境里的人区分开的建议。"
            "如果不确定，用“疑似”或“可能”。"
            "整体保持一小段话，越短越好。\n\n"
            f"上一版 memory：\n{previous_memory}\n\n"
            "当前定位摘要：\n"
            f"{json.dumps(self._compact_locate_result(locate_result), ensure_ascii=True)}"
        )
        output_contract = (
            "只返回 Markdown 正文。不要追加日志，不要分 section，不要使用 ``` 代码块围栏。尽量短。"
        )
        request_frames = [*(reference_frame_paths or []), *frame_paths]
        memory = self._client.complete_text(
            instruction=instruction,
            frame_paths=request_frames,
            output_contract=output_contract,
            temperature=0,
            max_tokens=180,
            model=self._sub_model,
        )
        return normalize_memory_markdown(memory)

    def answer_chat(
        self,
        memory_markdown: str,
        question: str,
        frame_paths: Sequence[Path],
        reference_frame_paths: Optional[Sequence[Path]] = None,
    ) -> str:
        memory_markdown = normalize_memory_markdown(memory_markdown)
        reference_block = (
            "第一张图片里的人就是目标人物；后面的图片是当前需要参考的场景帧。"
            if reference_frame_paths
            else "输入图片是当前需要参考的场景帧。"
        )
        instruction = (
            f"{reference_block}"
            "请结合当前图像和下面这份简短 tracking memory 回答用户问题。"
            "回答保持简短。"
            "如果是在推断，请明确说“可能”或“推测”。\n\n"
            f"当前 tracking memory：\n{memory_markdown}\n\n"
            f"用户问题：{question}"
        )
        output_contract = (
            "只返回简洁的纯文本回答，内容必须基于当前 memory 和图像帧。"
        )
        request_frames = [*(reference_frame_paths or []), *frame_paths]
        return self._client.complete_text(
            instruction=instruction,
            frame_paths=request_frames,
            output_contract=output_contract,
            temperature=0,
            max_tokens=160,
            model=self._sub_model,
        ).strip()
