from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from .pi_protocol import (
    DEFAULT_PI_BINARY,
    DEFAULT_PI_TIMEOUT_SECONDS,
    DEFAULT_PI_TOOLS,
    PiRpcClient,
    _build_pi_prompt,
    _build_pi_route_prompt,
)
from .route_context import build_route_context
from .session import AgentSession
from .session_store import AgentSessionStore
from backend.perception.service import LocalPerceptionService
from backend.skills import (
    installed_skill_names,
    project_skill_paths,
)

AGENT_RUNTIME_NAMESPACE = "agent_runtime"
ENABLED_SKILLS_FIELD = "enabled_skills"
TRACKING_SKILL_NAME = "tracking"
WEB_SEARCH_SKILL_NAME = "web_search"
FEISHU_SKILL_NAME = "feishu"
DESCRIBE_IMAGE_SKILL_NAME = "describe_image"


def normalize_enabled_skill_names(raw_skill_names: Any) -> list[str]:
    if raw_skill_names in (None, ""):
        return []

    raw_items: list[Any]
    if isinstance(raw_skill_names, str):
        raw_items = [raw_skill_names]
    elif isinstance(raw_skill_names, Iterable):
        raw_items = list(raw_skill_names)
    else:
        raw_items = [raw_skill_names]

    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        for chunk in str(item).split(","):
            cleaned = chunk.strip()
            if not cleaned or cleaned in seen:
                continue
            normalized.append(cleaned)
            seen.add(cleaned)
    return normalized


def available_project_skill_names() -> list[str]:
    return installed_skill_names()


def _project_skill_paths(enabled_skills: Any = None) -> list[Path]:
    return project_skill_paths(enabled_skills)


def _enabled_skills_in_session(session: AgentSession) -> list[str]:
    runtime_config = dict((session.environment.get(AGENT_RUNTIME_NAMESPACE) or {}))
    return normalize_enabled_skill_names(runtime_config.get(ENABLED_SKILLS_FIELD))


def _latest_user_text_for_routing(session: AgentSession) -> str:
    history = list(session.session.get("conversation_history") or [])
    for entry in reversed(history):
        if not isinstance(entry, dict):
            continue
        if str(entry.get("role", "")).strip() != "user":
            continue
        text = str(entry.get("text", "")).strip()
        if text:
            return text
    return ""


def _request_dir(artifacts_root: Path, session_id: str, request_id: str) -> Path:
    path = artifacts_root / "requests" / session_id / request_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _turn_context_payload(
    session: AgentSession,
    *,
    env_file: Path,
    artifacts_root: Path,
    request_id: str,
    enabled_skill_names: list[str],
    route_context_path: Path,
) -> Dict[str, Any]:
    return {
        "session_id": session.session_id,
        "request_id": request_id,
        "context_paths": {
            "route_context_path": str(route_context_path.resolve()),
        },
        "state_paths": dict(session.state_paths),
        "env_file": str(env_file.resolve()),
        "artifacts_root": str(artifacts_root.resolve()),
        "enabled_skills": list(enabled_skill_names),
    }


def _latest_perception_frame(session: AgentSession) -> Optional[Dict[str, Any]]:
    return LocalPerceptionService(Path(session.state_paths["state_root"])).read_latest_frame(session.session_id)


def _write_json(payload: Dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    return path


def _run_pi_turn(
    *,
    pi_binary: str,
    session: AgentSession,
    env_file: Path,
    artifacts_root: Path,
    request_id: str,
    pi_tools: str,
    enabled_skill_names: list[str],
    pi_timeout_seconds: int,
) -> Dict[str, Any]:
    request_dir = _request_dir(artifacts_root, session.session_id, request_id)
    route_context_path = _write_json(
        build_route_context(
            session,
            request_id=request_id,
            enabled_skill_names=enabled_skill_names,
            latest_frame=_latest_perception_frame(session),
        ),
        request_dir / "route_context.json",
    )
    turn_context_path = _write_json(
        _turn_context_payload(
            session,
            env_file=env_file,
            artifacts_root=artifacts_root,
            request_id=request_id,
            enabled_skill_names=enabled_skill_names,
            route_context_path=route_context_path,
        ),
        request_dir / "turn_context.json",
    )
    prompt_text = _build_pi_prompt(turn_context_path=turn_context_path)
    client = PiRpcClient.for_skills(
        pi_binary=pi_binary,
        pi_tools=pi_tools,
        enabled_skill_names=enabled_skill_names,
        env_file=env_file,
        timeout_seconds=pi_timeout_seconds,
    )
    return client.run_prompt(
        prompt_text=prompt_text,
        turn_context_path=turn_context_path,
        request_dir=request_dir,
    )


def _run_pi_route(
    *,
    pi_binary: str,
    session: AgentSession,
    env_file: Path,
    artifacts_root: Path,
    request_id: str,
    pi_tools: str,
    allowed_skill_names: list[str],
    pi_timeout_seconds: int,
) -> Dict[str, Any]:
    request_dir = _request_dir(artifacts_root, session.session_id, request_id) / "route_stage"
    route_context_path = _write_json(
        build_route_context(
            session,
            request_id=request_id,
            enabled_skill_names=allowed_skill_names,
            latest_frame=_latest_perception_frame(session),
        ),
        request_dir / "route_context.json",
    )
    turn_context_path = _write_json(
        _turn_context_payload(
            session,
            env_file=env_file,
            artifacts_root=artifacts_root,
            request_id=request_id,
            enabled_skill_names=allowed_skill_names,
            route_context_path=route_context_path,
        ),
        request_dir / "turn_context.json",
    )
    prompt_text = _build_pi_route_prompt(
        turn_context_path=turn_context_path,
        allowed_skill_names=allowed_skill_names,
    )
    client = PiRpcClient.for_skills(
        pi_binary=pi_binary,
        pi_tools=pi_tools,
        enabled_skill_names=allowed_skill_names,
        env_file=env_file,
        timeout_seconds=pi_timeout_seconds,
    )
    return client.run_route_prompt(
        prompt_text=prompt_text,
        turn_context_path=turn_context_path,
        request_dir=request_dir,
    )


def _as_optional_dict(value: Any, field_name: str) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object or null")
    return dict(value)


def _normalize_skill_state_patch(skill_name: str, patch: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if patch is None:
        return None
    nested = patch.get(skill_name)
    if len(patch) == 1 and isinstance(nested, dict):
        return dict(nested)
    return patch


def _schedule_rewrite_followup(
    *,
    skill_name: str,
    sessions: AgentSessionStore,
    session_id: str,
    rewrite_memory_input: Dict[str, Any],
    env_file: Path,
) -> None:
    if skill_name != TRACKING_SKILL_NAME:
        raise ValueError(f"rewrite_memory_input is not supported for skill: {skill_name}")

    from backend.tracking.deterministic import schedule_tracking_memory_rewrite

    schedule_tracking_memory_rewrite(
        sessions=sessions,
        session_id=session_id,
        rewrite_memory_input=rewrite_memory_input,
        env_file=env_file,
    )


def _maybe_run_sync_tracking_init_rewrite(
    *,
    sessions: AgentSessionStore,
    session_id: str,
    env_file: Path,
    rewrite_output: Optional[Dict[str, Any]],
    rewrite_memory_input: Optional[Dict[str, Any]],
) -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    if rewrite_output is not None:
        return rewrite_output, rewrite_memory_input
    if not isinstance(rewrite_memory_input, dict) or not rewrite_memory_input:
        return rewrite_output, rewrite_memory_input
    if str(rewrite_memory_input.get("task", "")).strip() != "init":
        return rewrite_output, rewrite_memory_input

    import backend.tracking.deterministic as tracking_orchestration_module

    session = sessions.load(session_id)
    resolved_rewrite_output = tracking_orchestration_module.execute_rewrite_memory_tool(
        session_file=Path(session.state_paths["session_path"]),
        arguments=dict(rewrite_memory_input),
        env_file=env_file,
    )
    tracking_orchestration_module.apply_tracking_rewrite_output(
        sessions=sessions,
        session_id=session_id,
        rewrite_output=resolved_rewrite_output,
    )
    return resolved_rewrite_output, None


class PiAgentRunner:
    def __init__(
        self,
        *,
        state_root: Path,
        frame_buffer_size: int = 3,
        pi_binary: str = DEFAULT_PI_BINARY,
        pi_tools: str = DEFAULT_PI_TOOLS,
        pi_timeout_seconds: int = DEFAULT_PI_TIMEOUT_SECONDS,
        enabled_skills: Any = None,
    ):
        self._sessions = AgentSessionStore(
            state_root=state_root,
            frame_buffer_size=frame_buffer_size,
        )
        self._pi_binary = str(pi_binary)
        self._pi_tools = pi_tools
        self._pi_timeout_seconds = int(pi_timeout_seconds)
        self._enabled_skills = normalize_enabled_skill_names(enabled_skills)

    @property
    def sessions(self) -> AgentSessionStore:
        return self._sessions

    def _enabled_skill_names_for_session(self, session: AgentSession) -> list[str]:
        resolved = (
            list(self._enabled_skills)
            if self._enabled_skills
            else _enabled_skills_in_session(session) or available_project_skill_names()
        )
        if DESCRIBE_IMAGE_SKILL_NAME in available_project_skill_names() and DESCRIBE_IMAGE_SKILL_NAME not in resolved:
            resolved.append(DESCRIBE_IMAGE_SKILL_NAME)
        return resolved

    def _run_agent_execution_path(
        self,
        *,
        session: AgentSession,
        request_id: str,
        env_file: Path,
        artifacts_root: Path,
        enabled_skill_names: list[str],
    ) -> Dict[str, Any]:
        pi_payload = _run_pi_turn(
            pi_binary=self._pi_binary,
            session=session,
            env_file=env_file,
            artifacts_root=artifacts_root,
            request_id=request_id,
            pi_tools=self._pi_tools,
            pi_timeout_seconds=self._pi_timeout_seconds,
            enabled_skill_names=enabled_skill_names,
        )

        status = str(pi_payload.get("status", "")).strip()
        if status == "idle":
            latest_observation = LocalPerceptionService(self._sessions.state_root).latest_camera_observation(
                session_id=session.session_id,
            )
            return {
                "session_id": session.session_id,
                "skill_name": None if pi_payload.get("skill_name") in (None, "") else str(pi_payload.get("skill_name")),
                "status": "idle",
                "frame_id": None
                if latest_observation is None
                else (latest_observation.get("payload") or {}).get("frame_id"),
                "reason": str(pi_payload.get("reason", "")).strip() or "No skill accepted the current turn.",
                "session": session.session,
            }
        return self._apply_processed_payload(
            session_id=session.session_id,
            pi_payload=pi_payload,
            env_file=env_file,
            base_session=session,
        )

    def process_chat_request(
        self,
        *,
        session_id: str,
        device_id: str,
        text: str,
        request_id: str,
        env_file: Path,
        artifacts_root: Path,
    ) -> Dict[str, Any]:
        session = self._sessions.append_chat_request(
            session_id=session_id,
            device_id=device_id,
            text=text,
            request_id=request_id,
        )
        allowed_skill_names = self._enabled_skill_names_for_session(session)
        route_payload = _run_pi_route(
            pi_binary=self._pi_binary,
            session=session,
            env_file=env_file,
            artifacts_root=artifacts_root,
            request_id=request_id,
            pi_tools=self._pi_tools,
            allowed_skill_names=allowed_skill_names,
            pi_timeout_seconds=self._pi_timeout_seconds,
        )
        decision = str(route_payload.get("decision", "")).strip()
        if decision == "direct_reply":
            reply_text = str(route_payload.get("reply_text", "")).strip()
            return self._apply_processed_payload(
                session_id=session.session_id,
                pi_payload={
                    "status": "processed",
                    "skill_name": "agent",
                    "session_result": {"behavior": "reply", "text": reply_text},
                    "latest_result_patch": None,
                    "skill_state_patch": None,
                    "user_preferences_patch": None,
                    "environment_map_patch": None,
                    "perception_cache_patch": None,
                    "robot_response": {"action": "reply", "text": reply_text},
                    "tool": "reply",
                    "tool_output": None,
                    "rewrite_output": None,
                    "rewrite_memory_input": None,
                    "reason": None,
                },
                env_file=env_file,
                base_session=session,
            )
        if decision == "idle":
            latest_observation = LocalPerceptionService(self._sessions.state_root).latest_camera_observation(
                session_id=session.session_id,
            )
            return {
                "session_id": session.session_id,
                "skill_name": None,
                "status": "idle",
                "frame_id": None
                if latest_observation is None
                else (latest_observation.get("payload") or {}).get("frame_id"),
                "reason": str(route_payload.get("reason", "")).strip() or "No route accepted the current turn.",
                "session": session.session,
            }
        if decision != "use_skills":
            raise ValueError(f"Unsupported route decision: {decision}")
        raw_skill_names = route_payload.get("skill_names")
        if not isinstance(raw_skill_names, list):
            raise ValueError("Route stage selected use_skills without skill_names")
        selected_skill_names = [str(name).strip() for name in raw_skill_names if str(name).strip()]
        if not selected_skill_names:
            raise ValueError("Route stage selected use_skills without any skill_names")
        return self._run_agent_execution_path(
            session=session,
            request_id=request_id,
            env_file=env_file,
            artifacts_root=artifacts_root,
            enabled_skill_names=selected_skill_names,
        )

    def process_session(
        self,
        *,
        session_id: str,
        request_id: str,
        env_file: Path,
        artifacts_root: Path,
    ) -> Dict[str, Any]:
        session = self._sessions.load(session_id)
        allowed_skill_names = self._enabled_skill_names_for_session(session)
        route_payload = _run_pi_route(
            pi_binary=self._pi_binary,
            session=session,
            env_file=env_file,
            artifacts_root=artifacts_root,
            request_id=request_id,
            pi_tools=self._pi_tools,
            allowed_skill_names=allowed_skill_names,
            pi_timeout_seconds=self._pi_timeout_seconds,
        )
        decision = str(route_payload.get("decision", "")).strip()
        if decision == "direct_reply":
            reply_text = str(route_payload.get("reply_text", "")).strip()
            return self._apply_processed_payload(
                session_id=session.session_id,
                pi_payload={
                    "status": "processed",
                    "skill_name": "agent",
                    "session_result": {"behavior": "reply", "text": reply_text},
                    "latest_result_patch": None,
                    "skill_state_patch": None,
                    "user_preferences_patch": None,
                    "environment_map_patch": None,
                    "perception_cache_patch": None,
                    "robot_response": {"action": "reply", "text": reply_text},
                    "tool": "reply",
                    "tool_output": None,
                    "rewrite_output": None,
                    "rewrite_memory_input": None,
                    "reason": None,
                },
                env_file=env_file,
                base_session=session,
            )
        if decision == "idle":
            latest_observation = LocalPerceptionService(self._sessions.state_root).latest_camera_observation(
                session_id=session.session_id,
            )
            return {
                "session_id": session.session_id,
                "skill_name": None,
                "status": "idle",
                "frame_id": None
                if latest_observation is None
                else (latest_observation.get("payload") or {}).get("frame_id"),
                "reason": str(route_payload.get("reason", "")).strip() or "No route accepted the current turn.",
                "session": session.session,
            }
        if decision != "use_skills":
            raise ValueError(f"Unsupported route decision: {decision}")
        raw_skill_names = route_payload.get("skill_names")
        if not isinstance(raw_skill_names, list):
            raise ValueError("Route stage selected use_skills without skill_names")
        selected_skill_names = [str(name).strip() for name in raw_skill_names if str(name).strip()]
        if not selected_skill_names:
            raise ValueError("Route stage selected use_skills without any skill_names")
        return self._run_agent_execution_path(
            session=session,
            request_id=request_id,
            env_file=env_file,
            artifacts_root=artifacts_root,
            enabled_skill_names=selected_skill_names,
        )

    def _apply_processed_payload(
        self,
        *,
        session_id: str,
        pi_payload: Dict[str, Any],
        env_file: Path,
        base_session: AgentSession | None = None,
    ) -> Dict[str, Any]:
        skill_name = str(pi_payload.get("skill_name", "")).strip()
        if not skill_name:
            raise ValueError("Processed Pi payload is missing skill_name")

        tool_output = _as_optional_dict(pi_payload.get("tool_output"), "tool_output")
        rewrite_output = _as_optional_dict(pi_payload.get("rewrite_output"), "rewrite_output")
        rewrite_memory_input = _as_optional_dict(pi_payload.get("rewrite_memory_input"), "rewrite_memory_input")
        session_result = _as_optional_dict(pi_payload.get("session_result"), "session_result")
        if session_result is None:
            raise ValueError("Processed Pi payload is missing session_result")
        robot_response = _as_optional_dict(pi_payload.get("robot_response"), "robot_response")

        if skill_name == TRACKING_SKILL_NAME:
            rewrite_output, rewrite_memory_input = _maybe_run_sync_tracking_init_rewrite(
                sessions=self._sessions,
                session_id=session_id,
                env_file=env_file,
                rewrite_output=rewrite_output,
                rewrite_memory_input=rewrite_memory_input,
            )
            if rewrite_output and str(session_result.get("behavior", "")).strip() == "init":
                from backend.tracking.memory import tracking_memory_display_text

                memory_text = tracking_memory_display_text(rewrite_output.get("memory", {})).strip()
                if memory_text:
                    session_result = dict(session_result)
                    base_text = str(session_result.get("text", "")).strip()
                    session_result["text"] = f"{base_text}\n{memory_text}".strip() if base_text else memory_text
                    if robot_response is not None:
                        robot_response = dict(robot_response)
                        base_robot_text = str(robot_response.get("text", "")).strip()
                        robot_response["text"] = f"{base_robot_text}\n{memory_text}".strip() if base_robot_text else memory_text

        self._sessions.apply_skill_result(
            session_id,
            session_result,
            base_session=base_session,
        )

        latest_result_patch = _as_optional_dict(pi_payload.get("latest_result_patch"), "latest_result_patch")
        if latest_result_patch:
            self._sessions.patch_latest_result(
                session_id=session_id,
                patch=latest_result_patch,
                expected_request_id=session_result.get("request_id"),
                expected_frame_id=session_result.get("frame_id"),
            )

        user_preferences_patch = _as_optional_dict(pi_payload.get("user_preferences_patch"), "user_preferences_patch")
        if user_preferences_patch:
            self._sessions.patch_user_preferences(session_id, user_preferences_patch)

        environment_map_patch = _as_optional_dict(pi_payload.get("environment_map_patch"), "environment_map_patch")
        if environment_map_patch:
            self._sessions.patch_environment(session_id, environment_map_patch)

        perception_cache_patch = _as_optional_dict(pi_payload.get("perception_cache_patch"), "perception_cache_patch")
        if perception_cache_patch:
            self._sessions.patch_perception(session_id, perception_cache_patch)

        skill_state_patch = _normalize_skill_state_patch(
            skill_name,
            _as_optional_dict(pi_payload.get("skill_state_patch"), "skill_state_patch"),
        )
        if skill_state_patch:
            self._sessions.patch_skill_state(
                session_id,
                skill_name=skill_name,
                patch=skill_state_patch,
            )

        if (
            skill_name == TRACKING_SKILL_NAME
            and rewrite_output
            and str(session_result.get("behavior", "")).strip() == "init"
        ):
            import backend.tracking.deterministic as tracking_orchestration_module

            tracking_orchestration_module.apply_tracking_rewrite_output(
                sessions=self._sessions,
                session_id=session_id,
                rewrite_output=rewrite_output,
            )

        if rewrite_memory_input:
            _schedule_rewrite_followup(
                skill_name=skill_name,
                sessions=self._sessions,
                session_id=session_id,
                rewrite_memory_input=rewrite_memory_input,
                env_file=env_file,
            )

        final_session = self._sessions.load(session_id)
        return {
            "session_id": session_id,
            "status": "processed",
            "skill_name": skill_name,
            "session_result": session_result,
            "latest_result_patch": latest_result_patch,
            "skill_state_patch": skill_state_patch,
            "user_preferences_patch": user_preferences_patch,
            "environment_map_patch": environment_map_patch,
            "perception_cache_patch": perception_cache_patch,
            "robot_response": robot_response or session_result.get("robot_response"),
            "tool": pi_payload.get("tool"),
            "tool_output": tool_output,
            "rewrite_output": rewrite_output,
            "rewrite_memory_input": rewrite_memory_input,
            "latest_result": final_session.latest_result,
            "session": final_session.session,
        }
