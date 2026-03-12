from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from tracking_agent.memory_format import normalize_memory_markdown


class DryRunTrackingBackend:
    def bootstrap_target(
        self,
        target_description: str,
        frame_paths: Sequence[Path],
    ) -> Dict[str, Any]:
        return {
            "found": True,
            "bbox": [10, 20, 110, 220],
            "confidence": 0.8,
            "reason": f"dry-run：已根据初始描述“{target_description}”返回占位初始 bbox。",
            "autonomous_inference": None,
            "needs_clarification": False,
            "clarification_question": None,
        }

    def initialize_memory(
        self,
        frame_paths: Sequence[Path],
        target_crop_path: Path,
        bootstrap_description: Optional[str] = None,
    ) -> str:
        return normalize_memory_markdown(
            "已根据最新目标裁剪图重建人物特征，后续不再依赖初始自然语言描述。"
            f" 下一轮优先参考截图 {target_crop_path.name}，比较目标与周围人的体型、发型、裤子、鞋子等差异。"
        )

    def locate_target(
        self,
        memory_markdown: str,
        frame_paths: Sequence[Path],
        reference_frame_paths: Optional[Sequence[Path]] = None,
        human_guidance: Optional[str] = None,
        edge_hint: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        newest_frame = frame_paths[-1].name if frame_paths else "unknown"
        reference_hint = (
            ",".join(path.name for path in reference_frame_paths)
            if reference_frame_paths
            else "none"
        )
        reason = (
            f"dry-run 模式：基于 {newest_frame} 返回占位 bbox，"
            f"上一确认整帧为 {reference_hint}。"
        )
        if human_guidance:
            reason += f" 已附加人工澄清：{human_guidance}"
        return {
            "found": True,
            "bbox": [10, 20, 110, 220],
            "confidence": 0.5,
            "reason": reason,
            "autonomous_inference": None,
            "needs_clarification": False,
            "clarification_question": None,
        }

    def rewrite_memory(
        self,
        previous_memory: str,
        locate_result: Dict[str, Any],
        frame_paths: Sequence[Path],
        reference_frame_paths: Optional[Sequence[Path]] = None,
    ) -> str:
        newest_frame = frame_paths[-1].name if frame_paths else "unknown"
        reference_hint = (
            ",".join(path.name for path in reference_frame_paths)
            if reference_frame_paths
            else "none"
        )
        return normalize_memory_markdown(
            "当前目标特征来自多张历史目标截图，并允许衣着等快变特征随时更新。"
            f" 下一轮继续结合上一确认整帧 {reference_hint}，区分 {newest_frame} 周围的相似人物。"
        )

    def answer_chat(
        self,
        memory_markdown: str,
        question: str,
        frame_paths: Sequence[Path],
        reference_frame_paths: Optional[Sequence[Path]] = None,
    ) -> str:
        newest_frame = frame_paths[-1].name if frame_paths else "unknown"
        reference_hint = (
            ",".join(path.name for path in reference_frame_paths)
            if reference_frame_paths
            else "none"
        )
        return (
            f"dry-run 模式下，最近一次上下文来自 {newest_frame}，"
            f"上一确认整帧是 {reference_hint}。"
        )
