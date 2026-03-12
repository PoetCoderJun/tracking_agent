from __future__ import annotations

import importlib.util
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from tracking_agent.backend_store import BackendSession
from tracking_agent.config import load_settings
from tracking_agent.detection_visualization import save_detection_visualization
from tracking_agent.memory_format import extract_memory_text, normalize_memory_markdown
from tracking_agent.target_crop import save_target_crop


SKILL_ROOT = Path(__file__).resolve().parents[1] / "skills" / "vision-tracking-skill"
AGENT_COMMON_PATH = SKILL_ROOT / "scripts" / "agent_common.py"
ROBOT_AGENT_CONFIG_PATH = SKILL_ROOT / "references" / "robot-agent-config.json"


def _load_agent_common() -> Any:
    spec = importlib.util.spec_from_file_location("vision_tracking_agent_common", AGENT_COMMON_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load agent_common from {AGENT_COMMON_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_AGENT_COMMON = _load_agent_common()
call_model = _AGENT_COMMON.call_model
load_agent_config = _AGENT_COMMON.load_agent_config
parse_json_block = _AGENT_COMMON.parse_json_block


SUPPORTED_ACTIONS = {"reply", "init", "track"}
GENERIC_CONTINUATION_TEXTS = {
    "持续跟踪",
    "继续跟踪",
    "继续追踪",
    "继续",
    "接着跟踪",
    "接着追踪",
    "保持跟踪",
}
INIT_INTENT_MARKERS = {
    "跟踪",
    "追踪",
    "锁定",
    "盯住",
    "找",
}


@dataclass(frozen=True)
class MemoryRewriteRequest:
    task: str
    crop_path: str
    frame_paths: List[str]
    frame_id: str
    target_id: int


def session_has_active_target(session: BackendSession) -> bool:
    return bool(
        session.latest_target_id is not None
        and session.latest_confirmed_frame_path
    )


def should_force_init(session: BackendSession, text: str) -> bool:
    cleaned_text = text.strip()
    if not cleaned_text or session_has_active_target(session):
        return False
    if cleaned_text in GENERIC_CONTINUATION_TEXTS:
        return False
    if session.pending_question:
        return True
    return any(marker in cleaned_text for marker in INIT_INTENT_MARKERS)


def normalize_orchestration_result(result: Dict[str, Any]) -> Dict[str, Any]:
    action = str(result.get("action", "")).strip().lower()
    if action not in SUPPORTED_ACTIONS:
        raise ValueError(f"Unsupported orchestrator action: {result.get('action')}")

    reply = str(result.get("reply", "")).strip()
    target_description = str(result.get("target_description", "")).strip()
    pending_question = result.get("pending_question")
    if pending_question is not None:
        pending_question = str(pending_question).strip() or None
    reason = str(result.get("reason", "")).strip()

    return {
        "action": action,
        "reply": reply,
        "target_description": target_description,
        "pending_question": pending_question,
        "reason": reason,
    }


def normalize_select_result(result: Dict[str, Any]) -> Dict[str, Any]:
    found = bool(result.get("found", False))
    target_id = result.get("target_id")
    if target_id is not None:
        target_id = int(target_id)

    needs_clarification = bool(result.get("needs_clarification", False))
    clarification_question = result.get("clarification_question")
    if clarification_question is not None:
        clarification_question = str(clarification_question).strip() or None
    if needs_clarification and not clarification_question:
        clarification_question = "请进一步说明你指的是哪一个候选人。"

    text = str(result.get("text", "")).strip()
    reason = str(result.get("reason", "")).strip()
    if not text:
        text = reason or ("我确认当前目标。" if found and target_id is not None else "我暂时无法确认目标。")

    return {
        "found": found and target_id is not None,
        "target_id": target_id,
        "text": text,
        "reason": reason,
        "needs_clarification": needs_clarification,
        "clarification_question": clarification_question,
    }


class CloudTrackingAgent:
    def __init__(
        self,
        env_path: Path,
        config_path: Path = ROBOT_AGENT_CONFIG_PATH,
    ):
        self._env_path = env_path
        self._settings = load_settings(env_path)
        self._config = load_agent_config(config_path)

    def run(
        self,
        session: BackendSession,
        session_dir: Path,
        text: str,
    ) -> Dict[str, Any]:
        cleaned_text = text.strip()
        if should_force_init(session, cleaned_text):
            result = self._run_select(
                session=session,
                session_dir=session_dir,
                text=cleaned_text or session.target_description,
                behavior="init",
            )
            result["target_description"] = cleaned_text or session.target_description
            return result

        orchestration = self._orchestrate(session, text)
        action = orchestration["action"]

        if action == "reply":
            existing_found = False
            if session.latest_result is not None:
                existing_found = bool(session.latest_result.get("found", False))
            reply_text = orchestration["reply"] or orchestration["pending_question"] or "请继续说明你想跟踪的人。"
            return {
                "behavior": "reply",
                "text": reply_text,
                "target_id": session.latest_target_id,
                "found": existing_found,
                "needs_clarification": orchestration["pending_question"] is not None,
                "clarification_question": orchestration["pending_question"],
                "memory": session.latest_memory,
                "latest_target_crop": session.latest_target_crop,
                "pending_question": orchestration["pending_question"],
            }

        if action == "init":
            target_description = orchestration["target_description"] or text.strip()
            result = self._run_select(
                session=session,
                session_dir=session_dir,
                text=target_description,
                behavior="init",
            )
            result["target_description"] = target_description
            return result

        if action == "track":
            if not session_has_active_target(session):
                reply_text = orchestration["reply"] or "请先告诉我现在要跟踪哪一个人。"
                pending_question = orchestration["pending_question"] or reply_text
                return {
                    "behavior": "reply",
                    "text": reply_text,
                    "target_id": session.latest_target_id,
                    "found": False,
                    "needs_clarification": True,
                    "clarification_question": pending_question,
                    "memory": session.latest_memory,
                    "latest_target_crop": session.latest_target_crop,
                    "pending_question": pending_question,
                }
            return self._run_select(
                session=session,
                session_dir=session_dir,
                text=text,
                behavior="track",
            )

        raise ValueError(f"Unsupported orchestrator action: {action}")

    def _orchestrate(
        self,
        session: BackendSession,
        text: str,
    ) -> Dict[str, Any]:
        latest_summary = "无"
        if session.latest_result:
            latest_summary = (
                f"behavior={session.latest_result.get('behavior')}, "
                f"target_id={session.latest_result.get('target_id')}, "
                f"found={session.latest_result.get('found')}, "
                f"text={session.latest_result.get('text')}"
            )

        instruction = str(self._config["prompts"]["orchestrator_prompt"]).format(
            target_description=session.target_description or "无",
            latest_target_id=session.latest_target_id,
            memory=extract_memory_text(session.latest_memory) or "无",
            pending_question=session.pending_question or "无",
            latest_result_summary=latest_summary,
            recent_dialogue=self._recent_dialogue(session),
            user_text=text.strip() or "(空输入)",
        )

        output = call_model(
            api_key=self._settings.api_key,
            base_url=self._settings.base_url,
            timeout_seconds=self._settings.timeout_seconds,
            model=self._settings.main_model,
            instruction=instruction,
            image_paths=[],
            output_contract=self._config["contracts"]["orchestrate_action"],
            max_tokens=int(self._config["limits"]["orchestrate_max_tokens"]),
        )
        return normalize_orchestration_result(parse_json_block(output["response_text"]))

    def _run_select(
        self,
        session: BackendSession,
        session_dir: Path,
        text: str,
        behavior: str,
    ) -> Dict[str, Any]:
        latest_frame = self._require_latest_frame(session)
        overlay_path = session_dir / "agent_artifacts" / f"{latest_frame.frame_id}_overlay.jpg"
        save_detection_visualization(
            image_path=Path(latest_frame.image_path),
            detections=latest_frame.detections,
            output_path=overlay_path,
        )

        candidate_summary = self._candidate_summary(latest_frame.detections)
        is_init = behavior == "init"
        recent_dialogue = self._recent_dialogue(session)

        if is_init:
            instruction = str(self._config["prompts"]["init_skill_prompt"]).format(
                target_description=text.strip() or session.target_description,
                candidates=candidate_summary,
            )
            image_paths = [overlay_path]
            output_contract = self._config["contracts"]["select_init_target"]
        else:
            instruction = str(self._config["prompts"]["track_skill_prompt"]).format(
                memory=extract_memory_text(session.latest_memory) or "无",
                latest_target_id=session.latest_target_id,
                candidates=candidate_summary,
                user_text=text.strip() or "继续跟踪",
                recent_dialogue=recent_dialogue,
            )
            historical_frame_path = Path(session.latest_confirmed_frame_path)
            if not historical_frame_path.exists():
                raise ValueError(
                    f"Session {session.session_id} is missing latest_confirmed_frame_path for tracking"
                )
            image_paths = [historical_frame_path, overlay_path]
            output_contract = self._config["contracts"]["select_track_target"]

        select_output = call_model(
            api_key=self._settings.api_key,
            base_url=self._settings.base_url,
            timeout_seconds=self._settings.timeout_seconds,
            model=self._settings.main_model,
            instruction=instruction,
            image_paths=image_paths,
            output_contract=output_contract,
            max_tokens=int(self._config["limits"]["select_max_tokens"]),
        )
        normalized = normalize_select_result(parse_json_block(select_output["response_text"]))
        crop_path = None
        memory_rewrite = None
        if normalized["found"]:
            crop_path = self._write_target_crop(
                session_dir,
                latest_frame.image_path,
                latest_frame.detections,
                normalized["target_id"],
            )
            if crop_path is not None:
                memory_rewrite = MemoryRewriteRequest(
                    task="init" if is_init else "update",
                    crop_path=str(crop_path),
                    frame_paths=[latest_frame.image_path],
                    frame_id=latest_frame.frame_id,
                    target_id=int(normalized["target_id"]),
                )

        return {
            "behavior": behavior,
            "text": normalized["text"],
            "target_id": normalized["target_id"],
            "found": normalized["found"],
            "needs_clarification": normalized["needs_clarification"],
            "clarification_question": normalized["clarification_question"],
            "memory": session.latest_memory,
            "reason": normalized["reason"],
            "latest_target_crop": None if crop_path is None else str(crop_path),
            "memory_rewrite": None if memory_rewrite is None else asdict(memory_rewrite),
            "pending_question": normalized["clarification_question"],
        }

    def rewrite_memory(
        self,
        request: MemoryRewriteRequest,
    ) -> str:
        prompt_key = "memory_init_prompt" if request.task == "init" else "memory_optimize_prompt"
        output = call_model(
            api_key=self._settings.api_key,
            base_url=self._settings.base_url,
            timeout_seconds=self._settings.timeout_seconds,
            model=self._settings.sub_model,
            instruction=self._config["prompts"][prompt_key],
            image_paths=[Path(request.crop_path), *[Path(path) for path in request.frame_paths]],
            output_contract=self._config["contracts"]["memory_markdown"],
            max_tokens=int(self._config["limits"]["memory_max_tokens"]),
        )
        return normalize_memory_markdown(output["response_text"])

    def _candidate_summary(self, detections: List[Any]) -> str:
        if not detections:
            return "- 无候选人"
        return "\n".join(
            f"- ID {int(detection.track_id)}: bbox={list(detection.bbox)}, score={float(detection.score):.2f}"
            for detection in detections
        )

    def _recent_dialogue(self, session: BackendSession) -> str:
        if not session.conversation_history:
            return "- 无"
        return "\n".join(
            f"- {entry.get('role', 'unknown')}: {entry.get('text', '')}"
            for entry in session.conversation_history[-6:]
        )

    def _write_target_crop(
        self,
        session_dir: Path,
        image_path: str,
        detections: List[Any],
        target_id: Optional[int],
    ) -> Optional[Path]:
        if target_id is None:
            return None
        for detection in detections:
            if int(detection.track_id) != int(target_id):
                continue
            crop_path = session_dir / "reference_crops" / f"{Path(image_path).stem}_id_{target_id}.jpg"
            save_target_crop(Path(image_path), detection.bbox, crop_path)
            return crop_path
        return None

    def _require_latest_frame(self, session: BackendSession):
        if not session.recent_frames:
            raise ValueError(f"Session {session.session_id} has no recent frames")
        return session.recent_frames[-1]
