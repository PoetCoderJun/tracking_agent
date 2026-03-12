from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from typing import Any, Callable, List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator

from tracking_agent.backend_store import BackendSession, BackendStore
from tracking_agent.cloud_agent import CloudTrackingAgent, MemoryRewriteRequest
from tracking_agent.config import load_settings


class FrontendUpdateBroker:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        with self._lock:
            self._connections.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        with self._lock:
            self._connections.discard(websocket)

    def publish(self, payload: dict) -> None:
        loop = self._loop
        if loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._broadcast(payload), loop)

    async def _broadcast(self, payload: dict) -> None:
        with self._lock:
            connections = tuple(self._connections)

        stale_connections: list[WebSocket] = []
        for websocket in connections:
            try:
                await websocket.send_json(payload)
            except Exception:  # pragma: no cover - disconnected sockets are best effort cleanup
                stale_connections.append(websocket)

        if stale_connections:
            with self._lock:
                for websocket in stale_connections:
                    self._connections.discard(websocket)

    async def close(self) -> None:
        with self._lock:
            connections = tuple(self._connections)
            self._connections.clear()
        for websocket in connections:
            try:
                await websocket.close()
            except Exception:  # pragma: no cover - disconnected sockets are already gone
                continue


class DetectionPayload(BaseModel):
    track_id: int
    bbox: List[int] = Field(..., min_items=4, max_items=4)
    score: float = 1.0
    label: str = "person"


class FramePayload(BaseModel):
    frame_id: str
    timestamp_ms: int
    image_path: Optional[str] = None
    image_url: Optional[str] = None
    image_base64: Optional[str] = None


class RobotIngestRequest(BaseModel):
    session_id: str
    device_id: str
    frame: FramePayload
    detections: List[DetectionPayload]
    text: str = ""


class AgentResultRequest(BaseModel):
    text: str
    behavior: str = "reply"
    target_id: Optional[int] = None
    bounding_box_id: Optional[int] = None
    bbox_id: Optional[int] = None
    found: bool = False
    needs_clarification: bool = False
    clarification_question: Optional[str] = None
    memory: str = ""
    target_description: str = ""
    pending_question: Optional[str] = None
    latest_target_crop: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def populate_target_id_aliases(cls, raw_value: Any) -> Any:
        if not isinstance(raw_value, dict):
            return raw_value
        payload = dict(raw_value)
        if payload.get("target_id") is None:
            alias_value = payload.get("bounding_box_id")
            if alias_value is None:
                alias_value = payload.get("bbox_id")
            if alias_value is not None:
                payload["target_id"] = alias_value
        return payload


class AgentRunRequest(BaseModel):
    text: str = ""


def _model_to_dict(model: BaseModel) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def create_app(
    state_root: Path,
    frame_buffer_size: int = 3,
    env_path: Path = Path(".ENV"),
    auto_run_agent: bool = True,
    agent_factory: Optional[Callable[[Path], Any]] = None,
    external_agent_wait_seconds: float = 0.0,
    external_agent_poll_seconds: float = 0.1,
) -> FastAPI:
    if external_agent_wait_seconds < 0:
        raise ValueError("external_agent_wait_seconds must be non-negative")
    if external_agent_poll_seconds <= 0:
        raise ValueError("external_agent_poll_seconds must be positive")

    store = BackendStore(state_root=state_root, frame_buffer_size=frame_buffer_size)
    broker = FrontendUpdateBroker()
    app = FastAPI(title="Tracking Agent Backend", version="0.1.0")
    auto_agent = None
    if auto_run_agent:
        if agent_factory is not None:
            auto_agent = agent_factory(env_path)
        elif load_settings(env_path).api_key:
            auto_agent = CloudTrackingAgent(env_path=env_path)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def frontend_state_payload(session: BackendSession) -> dict:
        latest_frame = session.recent_frames[-1] if session.recent_frames else None
        latest_frame_payload = None
        if latest_frame is not None:
            latest_frame_payload = {
                "frame_id": latest_frame.frame_id,
                "timestamp_ms": latest_frame.timestamp_ms,
                "image_url": f"/api/v1/sessions/{session.session_id}/frames/{latest_frame.frame_id}/image",
                "detections": [
                    {
                        **_model_to_dict(DetectionPayload(**detection.__dict__)),
                        "bounding_box_id": int(detection.track_id),
                    }
                    for detection in latest_frame.detections
                ],
            }

        return {
            "session_id": session.session_id,
            "device_id": session.device_id,
            "target_description": session.target_description,
            "latest_memory": session.latest_memory,
            "latest_target_id": session.latest_target_id,
            "latest_bounding_box_id": session.latest_target_id,
            "latest_result": session.latest_result,
            "result_history": session.result_history,
            "clarification_notes": session.clarification_notes,
            "conversation_history": session.conversation_history,
            "pending_question": session.pending_question,
            "latest_frame": latest_frame_payload,
            "updated_at": session.updated_at,
        }

    def publish_session_update(session: BackendSession, source: str) -> None:
        broker.publish(
            {
                "type": "session_update",
                "source": source,
                "session_id": session.session_id,
                "updated_at": session.updated_at,
            }
        )

    def wait_for_external_agent_result(
        session_id: str,
        expected_frame_id: str,
    ) -> Optional[BackendSession]:
        if external_agent_wait_seconds == 0:
            return None

        deadline = time.monotonic() + external_agent_wait_seconds
        while True:
            session = store.load_session(session_id)
            latest_result = session.latest_result or {}
            if latest_result.get("frame_id") == expected_frame_id:
                return session

            remaining_seconds = deadline - time.monotonic()
            if remaining_seconds <= 0:
                return None

            time.sleep(min(external_agent_poll_seconds, remaining_seconds))

    def maybe_run_auto_agent(session: BackendSession, text: str) -> tuple[BackendSession, Optional[str]]:
        if auto_agent is None:
            return session, None

        try:
            result = auto_agent.run(
                session=session,
                session_dir=store.session_dir(session.session_id),
                text=text,
            )
            updated_session = store.apply_agent_result(session.session_id, result)
            publish_session_update(updated_session, source="agent_result")

            rewrite_payload = result.get("memory_rewrite")
            if rewrite_payload:
                memory = auto_agent.rewrite_memory(MemoryRewriteRequest(**rewrite_payload))
                updated_session = store.apply_memory_update(
                    session_id=session.session_id,
                    memory=memory,
                    expected_frame_id=str(rewrite_payload["frame_id"]),
                    expected_target_id=int(rewrite_payload["target_id"]),
                    expected_target_crop=(
                        None
                        if rewrite_payload.get("crop_path") in (None, "")
                        else str(rewrite_payload["crop_path"])
                    ),
                )
                publish_session_update(updated_session, source="memory_update")
            return updated_session, None
        except Exception as exc:
            error_message = str(exc).strip() or exc.__class__.__name__
            updated_session = store.apply_agent_result(
                session.session_id,
                {
                    "behavior": "error",
                    "text": f"Agent request failed: {error_message}",
                    "target_id": session.latest_target_id,
                    "found": False,
                    "needs_clarification": False,
                    "clarification_question": None,
                    "memory": session.latest_memory,
                    "target_description": session.target_description,
                    "pending_question": session.pending_question,
                    "latest_target_crop": session.latest_target_crop,
                },
            )
            publish_session_update(updated_session, source="agent_error")
            return updated_session, error_message

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.on_event("startup")
    async def startup_broker() -> None:
        broker.attach_loop(asyncio.get_running_loop())

    @app.on_event("shutdown")
    async def shutdown_broker() -> None:
        await broker.close()

    @app.websocket("/ws/frontend-updates")
    async def frontend_updates(websocket: WebSocket) -> None:
        await broker.connect(websocket)
        await websocket.send_json({"type": "connected"})
        try:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    break
        except (RuntimeError, WebSocketDisconnect):
            pass
        finally:
            await broker.disconnect(websocket)

    @app.get("/api/v1/sessions")
    def list_sessions() -> dict:
        return {"sessions": store.list_sessions()}

    @app.post("/api/v1/robot/ingest")
    def ingest_robot_event(payload: RobotIngestRequest) -> dict:
        if not (payload.frame.image_base64 or payload.frame.image_path or payload.frame.image_url):
            raise HTTPException(
                status_code=400,
                detail="frame must include one of image_base64, image_path, or image_url",
            )
        session = store.ingest_robot_event(
            session_id=payload.session_id,
            device_id=payload.device_id,
            frame=_model_to_dict(payload.frame),
            detections=[_model_to_dict(item) for item in payload.detections],
            text=payload.text,
        )
        publish_session_update(session, source="ingest")
        session, agent_error = maybe_run_auto_agent(session, payload.text)
        latest_frame = session.recent_frames[-1]
        if auto_agent is None:
            waited_session = wait_for_external_agent_result(
                session_id=session.session_id,
                expected_frame_id=latest_frame.frame_id,
            )
            if waited_session is not None:
                session = waited_session

        latest_result = session.latest_result
        matched_agent_result = None
        if latest_result is not None and latest_result.get("frame_id") == latest_frame.frame_id:
            matched_agent_result = latest_result
        return {
            "session_id": session.session_id,
            "frame_id": latest_frame.frame_id,
            "recent_frame_count": len(session.recent_frames),
            "latest_memory": session.latest_memory,
            "latest_target_id": session.latest_target_id,
            "latest_result": matched_agent_result,
            "agent_behavior": None if matched_agent_result is None else matched_agent_result.get("behavior"),
            "agent_error": agent_error,
            "agent_required": matched_agent_result is None or agent_error is not None,
            "agent_context": store.build_agent_context(session.session_id),
            "agent_result_path": f"/api/v1/sessions/{session.session_id}/agent-result",
        }

    @app.get("/api/v1/sessions/{session_id}")
    def get_session(session_id: str) -> dict:
        try:
            return store.session_payload(session_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown session: {session_id}") from exc

    @app.get("/api/v1/sessions/{session_id}/frontend-state")
    def get_frontend_state(session_id: str) -> dict:
        try:
            session = store.load_session(session_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown session: {session_id}") from exc
        return frontend_state_payload(session)

    @app.post("/api/v1/sessions/{session_id}/clear")
    def clear_session(session_id: str) -> dict:
        try:
            session = store.clear_session(session_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown session: {session_id}") from exc
        publish_session_update(session, source="clear")
        return frontend_state_payload(session)

    @app.get("/api/v1/sessions/{session_id}/frames/{frame_id}/image")
    def get_frame_image(session_id: str, frame_id: str):
        try:
            image_path = store.frame_image_path(session_id, frame_id)
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown frame {frame_id} in session {session_id}",
            ) from exc
        if not image_path.exists():
            raise HTTPException(status_code=404, detail=f"Image file missing: {image_path}")
        return FileResponse(image_path)

    @app.get("/api/v1/sessions/{session_id}/agent-context")
    def get_agent_context(session_id: str) -> dict:
        try:
            return store.build_agent_context(session_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown session: {session_id}") from exc

    @app.post("/api/v1/sessions/{session_id}/agent-result")
    def post_agent_result(session_id: str, payload: AgentResultRequest) -> dict:
        try:
            session = store.apply_agent_result(session_id, _model_to_dict(payload))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown session: {session_id}") from exc
        publish_session_update(session, source="agent_result")
        return {
            "session_id": session.session_id,
            "latest_result": session.latest_result,
            "latest_target_id": session.latest_target_id,
            "latest_memory": session.latest_memory,
        }

    @app.post("/api/v1/sessions/{session_id}/run-agent")
    def run_agent(session_id: str, payload: AgentRunRequest) -> dict:
        raise HTTPException(
            status_code=410,
            detail=(
                "Local backend agent execution has been removed. "
                "Use /agent-context with the PI Agent, then submit the result to /agent-result."
            ),
        )

    return app
