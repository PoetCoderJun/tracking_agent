from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from typing import Any, List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError, model_validator

from tracking_agent.backend_store import BackendSession, BackendStore


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


class AgentResultWaiters:
    def __init__(self) -> None:
        self._events: dict[tuple[str, str], list[threading.Event]] = {}
        self._lock = threading.Lock()

    def register(self, session_id: str, frame_id: str) -> threading.Event:
        event = threading.Event()
        key = (session_id, frame_id)
        with self._lock:
            self._events.setdefault(key, []).append(event)
        return event

    def unregister(self, session_id: str, frame_id: str, event: threading.Event) -> None:
        key = (session_id, frame_id)
        with self._lock:
            waiters = self._events.get(key)
            if not waiters:
                return
            self._events[key] = [item for item in waiters if item is not event]
            if not self._events[key]:
                self._events.pop(key, None)

    def notify(self, session_id: str, frame_id: str) -> None:
        key = (session_id, frame_id)
        with self._lock:
            waiters = list(self._events.get(key, []))
        for event in waiters:
            event.set()


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
    frame_id: Optional[str] = None
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


class MemoryUpdateRequest(BaseModel):
    memory: str
    expected_frame_id: str
    expected_target_id: int
    expected_target_crop: Optional[str] = None


def _model_to_dict(model: BaseModel) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _displayable_result(session: BackendSession) -> Optional[dict]:
    entries = []
    if isinstance(session.latest_result, dict):
        entries.append(session.latest_result)
    entries.extend(reversed(session.result_history))
    for entry in entries:
        bbox = entry.get("bbox")
        if bool(entry.get("found")) and isinstance(bbox, list) and len(bbox) == 4:
            return entry
    return None


def create_app(
    state_root: Path,
    frame_buffer_size: int = 3,
    external_agent_wait_seconds: float = 0.0,
    external_agent_poll_seconds: float = 0.1,
) -> FastAPI:
    if external_agent_wait_seconds < 0:
        raise ValueError("external_agent_wait_seconds must be non-negative")
    if external_agent_poll_seconds <= 0:
        raise ValueError("external_agent_poll_seconds must be positive")

    store = BackendStore(state_root=state_root, frame_buffer_size=frame_buffer_size)
    broker = FrontendUpdateBroker()
    waiters = AgentResultWaiters()
    app = FastAPI(title="Tracking Agent Backend", version="0.1.0")
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
        display_frame_payload = None
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
        display_result = _displayable_result(session)
        if display_result is not None and session.latest_confirmed_frame_path:
            display_frame_payload = {
                "frame_id": display_result.get("frame_id"),
                "image_url": f"/api/v1/sessions/{session.session_id}/latest-confirmed-frame/image",
                "bbox": [int(value) for value in display_result["bbox"]],
                "target_id": (
                    None
                    if display_result.get("target_id") is None
                    else int(display_result["target_id"])
                ),
                "updated_at": display_result.get("updated_at"),
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
            "display_frame": display_frame_payload,
            "updated_at": session.updated_at,
        }

    def dashboard_payload(
        *,
        event_type: str,
        source: str,
        changed_session: Optional[BackendSession] = None,
    ) -> dict:
        sessions = store.list_sessions()
        active_session = changed_session
        if active_session is None and sessions:
            active_session = store.load_session(str(sessions[0]["session_id"]))
        return {
            "type": event_type,
            "source": source,
            "changed_session_id": None if changed_session is None else changed_session.session_id,
            "session_id": None if active_session is None else active_session.session_id,
            "updated_at": None if active_session is None else active_session.updated_at,
            "sessions": sessions,
            "frontend_state": None if active_session is None else frontend_state_payload(active_session),
        }

    def publish_session_update(session: BackendSession, source: str) -> None:
        broker.publish(
            dashboard_payload(
                event_type="session_update",
                source=source,
                changed_session=session,
            )
        )

    def wait_for_external_agent_result(
        session_id: str,
        expected_frame_id: str,
    ) -> Optional[BackendSession]:
        if external_agent_wait_seconds == 0:
            return None

        session = store.load_session(session_id)
        latest_result = session.latest_result or {}
        if latest_result.get("frame_id") == expected_frame_id:
            return session

        waiter = waiters.register(session_id, expected_frame_id)
        try:
            session = store.load_session(session_id)
            latest_result = session.latest_result or {}
            if latest_result.get("frame_id") == expected_frame_id:
                return session
            waiter.wait(timeout=external_agent_wait_seconds)
            session = store.load_session(session_id)
            latest_result = session.latest_result or {}
            if latest_result.get("frame_id") == expected_frame_id:
                return session
            return None
        finally:
            waiters.unregister(session_id, expected_frame_id, waiter)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.on_event("startup")
    async def startup_broker() -> None:
        broker.attach_loop(asyncio.get_running_loop())

    @app.on_event("shutdown")
    async def shutdown_broker() -> None:
        await broker.close()

    async def stream_session_events(websocket: WebSocket) -> None:
        await broker.connect(websocket)
        await websocket.send_json({"type": "connected"})
        await websocket.send_json(
            dashboard_payload(
                event_type="dashboard_state",
                source="snapshot",
            )
        )
        try:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    break
        except (RuntimeError, WebSocketDisconnect):
            pass
        finally:
            await broker.disconnect(websocket)

    @app.websocket("/ws/session-events")
    async def session_events(websocket: WebSocket) -> None:
        await stream_session_events(websocket)

    @app.websocket("/ws/frontend-updates")
    async def frontend_updates(websocket: WebSocket) -> None:
        await stream_session_events(websocket)

    @app.get("/api/v1/sessions")
    def list_sessions() -> dict:
        return {"sessions": store.list_sessions()}

    def handle_robot_ingest(payload: RobotIngestRequest) -> dict:
        if not (payload.frame.image_base64 or payload.frame.image_path or payload.frame.image_url):
            raise ValueError("frame must include one of image_base64, image_path, or image_url")
        session = store.ingest_robot_event(
            session_id=payload.session_id,
            device_id=payload.device_id,
            frame=_model_to_dict(payload.frame),
            detections=[_model_to_dict(item) for item in payload.detections],
            text=payload.text,
        )
        publish_session_update(session, source="ingest")
        latest_frame = session.recent_frames[-1]
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
            "agent_error": None,
            "agent_required": matched_agent_result is None,
            "session_path": f"/api/v1/sessions/{session.session_id}",
            "agent_result_path": f"/api/v1/sessions/{session.session_id}/agent-result",
        }

    @app.post("/api/v1/robot/ingest")
    def ingest_robot_event(payload: RobotIngestRequest) -> dict:
        try:
            return handle_robot_ingest(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.websocket("/ws/robot-ingest")
    async def robot_ingest_stream(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            while True:
                payload_raw = await websocket.receive_json()
                try:
                    payload = RobotIngestRequest(**payload_raw)
                    result = await asyncio.to_thread(handle_robot_ingest, payload)
                except ValidationError as exc:
                    await websocket.send_json(
                        {
                            "type": "robot_ingest_error",
                            "status": 400,
                            "error": str(exc),
                        }
                    )
                    continue
                except ValueError as exc:
                    await websocket.send_json(
                        {
                            "type": "robot_ingest_error",
                            "status": 400,
                            "error": str(exc),
                        }
                    )
                    continue

                await websocket.send_json(
                    {
                        "type": "robot_ingest_result",
                        "status": 200,
                        "payload": result,
                    }
                )
        except (RuntimeError, WebSocketDisconnect):
            pass

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

    @app.get("/api/v1/sessions/{session_id}/latest-confirmed-frame/image")
    def get_latest_confirmed_frame_image(session_id: str):
        try:
            session = store.load_session(session_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown session: {session_id}") from exc
        if not session.latest_confirmed_frame_path:
            raise HTTPException(status_code=404, detail=f"No confirmed frame for session {session_id}")
        image_path = Path(session.latest_confirmed_frame_path)
        if not image_path.exists():
            raise HTTPException(status_code=404, detail=f"Image file missing: {image_path}")
        return FileResponse(image_path)

    @app.post("/api/v1/sessions/{session_id}/agent-result")
    def post_agent_result(session_id: str, payload: AgentResultRequest) -> dict:
        try:
            session = store.apply_agent_result(session_id, _model_to_dict(payload))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown session: {session_id}") from exc
        latest_result = session.latest_result or {}
        if latest_result.get("frame_id") not in (None, ""):
            waiters.notify(session.session_id, str(latest_result["frame_id"]))
        publish_session_update(session, source="agent_result")
        return {
            "session_id": session.session_id,
            "latest_result": session.latest_result,
            "latest_target_id": session.latest_target_id,
            "latest_memory": session.latest_memory,
        }

    @app.post("/api/v1/sessions/{session_id}/memory-update")
    def post_memory_update(session_id: str, payload: MemoryUpdateRequest) -> dict:
        try:
            session = store.apply_memory_update(
                session_id=session_id,
                memory=payload.memory,
                expected_frame_id=payload.expected_frame_id,
                expected_target_id=payload.expected_target_id,
                expected_target_crop=payload.expected_target_crop,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown session: {session_id}") from exc
        publish_session_update(session, source="memory_update")
        return {
            "session_id": session.session_id,
            "latest_memory": session.latest_memory,
            "latest_result": session.latest_result,
        }

    return app
