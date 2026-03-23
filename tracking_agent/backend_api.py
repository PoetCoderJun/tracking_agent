from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any, List, Optional, Sequence

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError, model_validator

from tracking_agent.backend_store import BackendSession, BackendStore
from tracking_agent.service_urls import join_url_path, normalize_base_url

try:
    import socketio
except ImportError:  # pragma: no cover - dependency is declared in project metadata
    socketio = None


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
    request_id: Optional[str] = None
    function: Optional[str] = None
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
    robot_response: Optional[dict[str, Any]] = None

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


class RobotAgentRequest(BaseModel):
    request_id: str
    session_id: str
    function: str
    text: str = ""
    frame_id: Optional[str] = None
    timestamp_ms: Optional[int] = None
    device_id: str = ""
    image_base64: Optional[str] = None
    detections: List[DetectionPayload] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_request(self) -> "RobotAgentRequest":
        normalized_function = self.function.strip().lower()
        if normalized_function not in {"tracking", "chat"}:
            raise ValueError("function must be one of: tracking, chat")
        if normalized_function == "tracking":
            if not self.frame_id:
                raise ValueError("tracking request requires frame_id")
            if self.timestamp_ms is None:
                raise ValueError("tracking request requires timestamp_ms")
            if not self.image_base64:
                raise ValueError("tracking request requires image_base64")
            if not self.device_id.strip():
                raise ValueError("tracking request requires device_id")
        self.function = normalized_function
        self.request_id = self.request_id.strip()
        self.session_id = self.session_id.strip()
        self.device_id = self.device_id.strip()
        self.text = self.text.strip()
        return self


def _normalize_cors_origins(cors_origins: Optional[Sequence[str]]) -> List[str]:
    if cors_origins is None:
        return ["*"]
    normalized = [str(origin).strip() for origin in cors_origins if str(origin).strip()]
    return normalized or ["*"]


def _safe_frontend_asset(frontend_root: Path, relative_path: str) -> Optional[Path]:
    candidate = (frontend_root / relative_path.lstrip("/")).resolve()
    try:
        candidate.relative_to(frontend_root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


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


def _matched_agent_result(
    session: BackendSession,
    frame_id: Optional[str] = None,
    request_id: Optional[str] = None,
) -> Optional[dict]:
    latest_result = session.latest_result
    if latest_result is None:
        return None
    if request_id is not None and latest_result.get("request_id") == request_id:
        return latest_result
    if frame_id is not None and latest_result.get("frame_id") == frame_id:
        return latest_result
    return None


def create_app(
    state_root: Path,
    frame_buffer_size: int = 3,
    external_agent_wait_seconds: float = 0.0,
    external_agent_poll_seconds: float = 0.1,
    public_base_url: Optional[str] = None,
    cors_origins: Optional[Sequence[str]] = None,
    frontend_dist: Optional[Path] = None,
) -> Any:
    if external_agent_wait_seconds < 0:
        raise ValueError("external_agent_wait_seconds must be non-negative")
    if external_agent_poll_seconds <= 0:
        raise ValueError("external_agent_poll_seconds must be positive")

    frontend_root: Optional[Path] = None
    if frontend_dist is not None:
        frontend_root = Path(frontend_dist).resolve()
        index_path = frontend_root / "index.html"
        if not frontend_root.exists():
            raise ValueError(f"frontend_dist does not exist: {frontend_root}")
        if not index_path.exists():
            raise ValueError(f"frontend_dist is missing index.html: {index_path}")

    normalized_public_base_url = None
    if public_base_url not in (None, ""):
        normalized_public_base_url = normalize_base_url(str(public_base_url))

    store = BackendStore(state_root=state_root, frame_buffer_size=frame_buffer_size)
    broker = FrontendUpdateBroker()
    waiters = AgentResultWaiters()
    app = FastAPI(title="Tracking Agent Backend", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_normalize_cors_origins(cors_origins),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    if socketio is None:
        raise RuntimeError("Missing backend dependency: python-socketio")
    socketio_cors_origins: Any = _normalize_cors_origins(cors_origins)
    if socketio_cors_origins == ["*"]:
        socketio_cors_origins = "*"
    sio = socketio.AsyncServer(
        async_mode="asgi",
        cors_allowed_origins=socketio_cors_origins,
    )

    def public_url(path: str) -> str:
        if normalized_public_base_url is None:
            return path
        return join_url_path(normalized_public_base_url, path)

    def frontend_state_payload(session: BackendSession) -> dict:
        latest_frame = session.recent_frames[-1] if session.recent_frames else None
        latest_frame_payload = None
        display_frame_payload = None
        if latest_frame is not None:
            latest_frame_payload = {
                "frame_id": latest_frame.frame_id,
                "timestamp_ms": latest_frame.timestamp_ms,
                "image_url": public_url(
                    f"/api/v1/sessions/{session.session_id}/frames/{latest_frame.frame_id}/image"
                ),
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
                "image_url": public_url(
                    f"/api/v1/sessions/{session.session_id}/latest-confirmed-frame/image"
                ),
                "bbox": [int(value) for value in display_result["bbox"]],
                "detections": [
                    {
                        **_model_to_dict(DetectionPayload(**detection.__dict__)),
                        "bounding_box_id": int(detection.track_id),
                    }
                    for detection in session.latest_confirmed_detections
                ],
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
            "latest_request_id": session.latest_request_id,
            "latest_request_function": session.latest_request_function,
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

    def ingest_robot_event_to_session(
        payload: RobotIngestRequest,
        *,
        request_id: Optional[str] = None,
        request_function: Optional[str] = None,
    ) -> tuple[BackendSession, str]:
        if not (payload.frame.image_base64 or payload.frame.image_path or payload.frame.image_url):
            raise ValueError("frame must include one of image_base64, image_path, or image_url")
        session = store.ingest_robot_event(
            session_id=payload.session_id,
            device_id=payload.device_id,
            frame=_model_to_dict(payload.frame),
            detections=[_model_to_dict(item) for item in payload.detections],
            text=payload.text,
            request_id=request_id,
            request_function=request_function,
        )
        publish_session_update(session, source="ingest")
        latest_frame = session.recent_frames[-1]
        return session, latest_frame.frame_id

    def robot_ingest_response_payload(session: BackendSession, frame_id: str) -> dict:
        matched_agent_result = _matched_agent_result(session, frame_id)
        return {
            "session_id": session.session_id,
            "frame_id": frame_id,
            "recent_frame_count": len(session.recent_frames),
            "latest_memory": session.latest_memory,
            "latest_target_id": session.latest_target_id,
            "latest_result": matched_agent_result,
            "agent_behavior": None if matched_agent_result is None else matched_agent_result.get("behavior"),
            "agent_error": None,
            "agent_required": matched_agent_result is None,
            "session_path": public_url(f"/api/v1/sessions/{session.session_id}"),
            "agent_result_path": public_url(f"/api/v1/sessions/{session.session_id}/agent-result"),
        }

    def normalize_robot_agent_payload(
        payload: dict[str, Any],
        request: RobotAgentRequest,
    ) -> dict:
        normalized = dict(payload)
        normalized["request_id"] = str(normalized.get("request_id") or request.request_id)
        normalized["session_id"] = str(normalized.get("session_id") or request.session_id)
        normalized["function"] = str(normalized.get("function") or request.function)

        if request.function == "chat":
            normalized["text"] = str(normalized.get("text", "")).strip()
            return normalized

        normalized["frame_id"] = str(normalized.get("frame_id") or request.frame_id)
        action = str(normalized.get("action", "wait")).strip().lower() or "wait"
        if action not in {"wait", "ask", "track", "stop"}:
            action = "wait"
        normalized["action"] = action
        normalized["text"] = str(normalized.get("text", "")).strip() or "等待云端结果。"
        if action == "track" and normalized.get("target_id") is not None:
            normalized["target_id"] = int(normalized["target_id"])
        else:
            normalized.pop("target_id", None)
        return normalized

    def robot_agent_response_payload(
        session: BackendSession,
        request: RobotAgentRequest,
    ) -> dict:
        matched_agent_result = _matched_agent_result(session, request_id=request.request_id)
        if matched_agent_result is not None:
            robot_response = matched_agent_result.get("robot_response")
            if isinstance(robot_response, dict):
                return normalize_robot_agent_payload(robot_response, request)

        if request.function == "chat":
            return {
                "request_id": request.request_id,
                "session_id": request.session_id,
                "function": "chat",
                "text": (
                    "等待云端结果。"
                    if matched_agent_result is None
                    else str(matched_agent_result.get("text", "")).strip()
                ),
            }

        return {
            "request_id": request.request_id,
            "session_id": request.session_id,
            "function": "tracking",
            "frame_id": request.frame_id,
            "action": "wait",
            "text": (
                "等待云端结果。"
                if matched_agent_result is None
                else str(matched_agent_result.get("text", "")).strip() or "等待云端结果。"
            ),
        }

    def handle_robot_agent_request(payload: RobotAgentRequest) -> dict:
        if payload.function == "tracking":
            ingest_payload = RobotIngestRequest(
                session_id=payload.session_id,
                device_id=payload.device_id,
                frame=FramePayload(
                    frame_id=str(payload.frame_id),
                    timestamp_ms=int(payload.timestamp_ms),
                    image_base64=payload.image_base64,
                ),
                detections=payload.detections,
                text=payload.text,
            )
            session, frame_id = ingest_robot_event_to_session(
                ingest_payload,
                request_id=payload.request_id,
                request_function=payload.function,
            )
            waited_session = wait_for_external_agent_result(
                session_id=session.session_id,
                expected_frame_id=frame_id,
                expected_request_id=payload.request_id,
            )
            if waited_session is not None:
                session = waited_session
            return robot_agent_response_payload(session, payload)

        session = store.append_chat_request(
            session_id=payload.session_id,
            device_id=payload.device_id or "robot_01",
            text=payload.text,
            request_id=payload.request_id,
        )
        publish_session_update(session, source="chat")
        waited_session = wait_for_external_agent_result(
            session_id=session.session_id,
            expected_request_id=payload.request_id,
        )
        if waited_session is not None:
            session = waited_session
        return robot_agent_response_payload(session, payload)

    def stale_robot_agent_payload(payload: RobotAgentRequest) -> dict:
        return {
            "request_id": payload.request_id,
            "session_id": payload.session_id,
            "function": payload.function,
            "stale_ignored": True,
        }

    async def execute_robot_agent_request(
        payload: RobotAgentRequest,
        *,
        return_stale_payload: bool,
    ) -> Optional[dict]:
        try:
            response = await asyncio.to_thread(handle_robot_agent_request, payload)
            latest_session = store.load_session(payload.session_id)
            if latest_session.latest_request_id != payload.request_id:
                return stale_robot_agent_payload(payload) if return_stale_payload else None
            return response
        except asyncio.CancelledError:
            return stale_robot_agent_payload(payload) if return_stale_payload else None
        except Exception as exc:
            latest_request_id = None
            try:
                latest_request_id = store.load_session(payload.session_id).latest_request_id
            except FileNotFoundError:
                latest_request_id = payload.request_id
            if latest_request_id != payload.request_id:
                return stale_robot_agent_payload(payload) if return_stale_payload else None
            return {
                "request_id": payload.request_id,
                "session_id": payload.session_id,
                "function": payload.function,
                "error": str(exc),
            }

    def wait_for_external_agent_result(
        session_id: str,
        expected_frame_id: Optional[str] = None,
        expected_request_id: Optional[str] = None,
    ) -> Optional[BackendSession]:
        if external_agent_wait_seconds == 0:
            return None

        session = store.load_session(session_id)
        latest_result = _matched_agent_result(
            session,
            frame_id=expected_frame_id,
            request_id=expected_request_id,
        )
        if latest_result is not None:
            return session

        waiter_key = expected_request_id or expected_frame_id
        if waiter_key is None:
            return None
        waiter = waiters.register(session_id, waiter_key)
        try:
            session = store.load_session(session_id)
            latest_result = _matched_agent_result(
                session,
                frame_id=expected_frame_id,
                request_id=expected_request_id,
            )
            if latest_result is not None:
                return session
            waiter.wait(timeout=external_agent_wait_seconds)
            session = store.load_session(session_id)
            latest_result = _matched_agent_result(
                session,
                frame_id=expected_frame_id,
                request_id=expected_request_id,
            )
            if latest_result is not None:
                return session
            return None
        finally:
            waiters.unregister(session_id, waiter_key, waiter)

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
        session, frame_id = ingest_robot_event_to_session(payload)
        waited_session = wait_for_external_agent_result(
            session_id=session.session_id,
            expected_frame_id=frame_id,
        )
        if waited_session is not None:
            session = waited_session
        return robot_ingest_response_payload(session, frame_id)

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
                    session, frame_id = await asyncio.to_thread(ingest_robot_event_to_session, payload)
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
                        "type": "robot_ingest_ack",
                        "status": 202,
                        "session_id": session.session_id,
                        "frame_id": frame_id,
                    }
                )

                if _matched_agent_result(session, frame_id) is None and external_agent_wait_seconds > 0:
                    await websocket.send_json(
                        {
                            "type": "robot_ingest_status",
                            "status": 202,
                            "stage": "waiting_for_agent",
                            "session_id": session.session_id,
                            "frame_id": frame_id,
                            "timeout_seconds": external_agent_wait_seconds,
                        }
                    )

                waited_session = await asyncio.to_thread(
                    wait_for_external_agent_result,
                    session.session_id,
                    frame_id,
                )
                if waited_session is not None:
                    session = waited_session
                    await websocket.send_json(
                        {
                            "type": "robot_ingest_status",
                            "status": 200,
                            "stage": "agent_result_received",
                            "session_id": session.session_id,
                            "frame_id": frame_id,
                        }
                    )
                elif _matched_agent_result(session, frame_id) is None and external_agent_wait_seconds > 0:
                    await websocket.send_json(
                        {
                            "type": "robot_ingest_status",
                            "status": 204,
                            "stage": "agent_timeout",
                            "session_id": session.session_id,
                            "frame_id": frame_id,
                        }
                    )

                result = robot_ingest_response_payload(session, frame_id)
                await websocket.send_json(
                    {
                        "type": "robot_ingest_result",
                        "status": 200,
                        "payload": result,
                    }
                )
        except (RuntimeError, WebSocketDisconnect):
            pass

    @app.websocket("/ws/robot-agent")
    async def robot_agent_stream(websocket: WebSocket) -> None:
        await websocket.accept()
        send_lock = asyncio.Lock()
        pending_tasks: dict[str, asyncio.Task[None]] = {}

        async def send_json(payload: dict) -> None:
            async with send_lock:
                await websocket.send_json(payload)

        async def process_request(payload: RobotAgentRequest) -> None:
            try:
                response = await execute_robot_agent_request(
                    payload,
                    return_stale_payload=False,
                )
                if response is not None:
                    await send_json(response)
            finally:
                current = pending_tasks.get(payload.session_id)
                if current is asyncio.current_task():
                    pending_tasks.pop(payload.session_id, None)

        try:
            while True:
                payload_raw = await websocket.receive_json()
                try:
                    payload = RobotAgentRequest(**payload_raw)
                except ValidationError as exc:
                    await send_json(
                        {
                            "request_id": payload_raw.get("request_id"),
                            "session_id": payload_raw.get("session_id"),
                            "function": payload_raw.get("function"),
                            "error": str(exc),
                        }
                    )
                    continue

                previous_task = pending_tasks.get(payload.session_id)
                if previous_task is not None:
                    previous_task.cancel()

                pending_tasks[payload.session_id] = asyncio.create_task(process_request(payload))
        except (RuntimeError, WebSocketDisconnect):
            pass
        finally:
            tasks = list(pending_tasks.values())
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    socketio_pending_tasks: dict[str, asyncio.Task[Optional[dict]]] = {}

    async def _handle_socketio_robot_agent(payload_raw: dict) -> dict:
        try:
            payload = RobotAgentRequest(**payload_raw)
        except ValidationError as exc:
            return {
                "request_id": payload_raw.get("request_id"),
                "session_id": payload_raw.get("session_id"),
                "function": payload_raw.get("function"),
                "error": str(exc),
            }

        previous_task = socketio_pending_tasks.get(payload.session_id)
        if previous_task is not None:
            previous_task.cancel()

        task = asyncio.create_task(
            execute_robot_agent_request(
                payload,
                return_stale_payload=True,
            )
        )
        socketio_pending_tasks[payload.session_id] = task
        try:
            response = await task
        finally:
            current = socketio_pending_tasks.get(payload.session_id)
            if current is task:
                socketio_pending_tasks.pop(payload.session_id, None)
        if response is None:
            return stale_robot_agent_payload(payload)
        return response

    @sio.on("robot-agent-request")
    async def socketio_robot_agent_request(sid: str, payload_raw: dict) -> dict:
        return await _handle_socketio_robot_agent(payload_raw)

    @sio.on("robot_agent_request")
    async def socketio_robot_agent_request_alias(sid: str, payload_raw: dict) -> dict:
        return await _handle_socketio_robot_agent(payload_raw)

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
        raw_payload = _model_to_dict(payload)
        try:
            session = store.apply_agent_result(session_id, raw_payload)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown session: {session_id}") from exc
        request_id = raw_payload.get("request_id")
        latest_result = session.latest_result or {}
        stale_ignored = bool(
            request_id not in (None, "")
            and latest_result.get("request_id") != request_id
        )
        if not stale_ignored:
            if latest_result.get("request_id") not in (None, ""):
                waiters.notify(session.session_id, str(latest_result["request_id"]))
            if latest_result.get("frame_id") not in (None, ""):
                waiters.notify(session.session_id, str(latest_result["frame_id"]))
            publish_session_update(session, source="agent_result")
        return {
            "session_id": session.session_id,
            "latest_result": session.latest_result,
            "latest_target_id": session.latest_target_id,
            "latest_memory": session.latest_memory,
            "stale_ignored": stale_ignored,
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

    @app.post("/api/v1/sessions/{session_id}/reset-context")
    def post_reset_context(session_id: str) -> dict:
        try:
            session = store.reset_tracking_context(session_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown session: {session_id}") from exc
        publish_session_update(session, source="reset_context")
        return {
            "session_id": session.session_id,
            "latest_memory": session.latest_memory,
            "latest_target_id": session.latest_target_id,
            "latest_result": session.latest_result,
            "frontend_state": frontend_state_payload(session),
        }

    if frontend_root is not None:
        frontend_index = frontend_root / "index.html"

        @app.get("/")
        def serve_frontend_index():
            return FileResponse(frontend_index)

        @app.get("/{full_path:path}")
        def serve_frontend_app(full_path: str):
            if full_path == "healthz" or full_path.startswith("api/") or full_path.startswith("ws/"):
                raise HTTPException(status_code=404, detail=f"Unknown path: /{full_path}")
            asset_path = _safe_frontend_asset(frontend_root, full_path)
            if asset_path is not None:
                return FileResponse(asset_path)
            return FileResponse(frontend_index)

    return socketio.ASGIApp(sio, other_asgi_app=app, socketio_path="socket.io")
