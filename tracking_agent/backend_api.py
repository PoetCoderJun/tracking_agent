from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from tracking_agent.backend_store import BackendSession, BackendStore
from tracking_agent.cloud_agent import CloudTrackingAgent, MemoryRewriteRequest


LOGGER = logging.getLogger(__name__)


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
    target_id: Optional[int] = None
    found: bool = False
    needs_clarification: bool = False
    clarification_question: Optional[str] = None
    memory: str = ""


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
) -> FastAPI:
    store = BackendStore(state_root=state_root, frame_buffer_size=frame_buffer_size)
    agent = CloudTrackingAgent(env_path=env_path)
    memory_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="memory-rewrite")
    broker = FrontendUpdateBroker()
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
        if latest_frame is not None:
            latest_frame_payload = {
                "frame_id": latest_frame.frame_id,
                "timestamp_ms": latest_frame.timestamp_ms,
                "image_url": f"/api/v1/sessions/{session.session_id}/frames/{latest_frame.frame_id}/image",
                "detections": [_model_to_dict(DetectionPayload(**detection.__dict__)) for detection in latest_frame.detections],
            }

        return {
            "session_id": session.session_id,
            "device_id": session.device_id,
            "target_description": session.target_description,
            "latest_memory": session.latest_memory,
            "latest_target_id": session.latest_target_id,
            "latest_result": session.latest_result,
            "result_history": session.result_history,
            "clarification_notes": session.clarification_notes,
            "conversation_history": session.conversation_history,
            "pending_question": session.pending_question,
            "latest_frame": latest_frame_payload,
            "updated_at": session.updated_at,
        }

    def schedule_memory_rewrite(session_id: str, result: dict) -> None:
        payload = result.get("memory_rewrite")
        if not payload:
            return

        request = MemoryRewriteRequest(**payload)

        def worker() -> None:
            try:
                rewritten_memory = agent.rewrite_memory(request)
                updated = store.apply_memory_update(
                    session_id=session_id,
                    memory=rewritten_memory,
                    expected_frame_id=request.frame_id,
                    expected_target_id=request.target_id,
                    expected_target_crop=request.crop_path,
                )
                publish_session_update(updated, source="memory_rewrite")
            except Exception as exc:  # pragma: no cover - background failures are integration concerns
                LOGGER.warning(
                    "Background memory rewrite failed for session %s frame %s: %s",
                    session_id,
                    request.frame_id,
                    exc,
                )

        memory_executor.submit(worker)

    def publish_session_update(session: BackendSession, source: str) -> None:
        broker.publish(
            {
                "type": "session_update",
                "source": source,
                "session_id": session.session_id,
                "updated_at": session.updated_at,
            }
        )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.on_event("startup")
    async def startup_broker() -> None:
        broker.attach_loop(asyncio.get_running_loop())

    @app.on_event("shutdown")
    async def shutdown_executor() -> None:
        memory_executor.shutdown(wait=False)
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
        agent_error = None
        agent_behavior = None
        try:
            result = agent.run(
                session=session,
                session_dir=store.session_dir(payload.session_id),
                text=payload.text,
            )
            session = store.apply_agent_result(payload.session_id, result)
            publish_session_update(session, source="agent_result")
            schedule_memory_rewrite(payload.session_id, result)
            agent_behavior = result["behavior"]
        except Exception as exc:  # pragma: no cover - network/model failures are integration concerns
            agent_error = str(exc)
        latest_frame = session.recent_frames[-1]
        return {
            "session_id": session.session_id,
            "frame_id": latest_frame.frame_id,
            "recent_frame_count": len(session.recent_frames),
            "latest_memory": session.latest_memory,
            "latest_target_id": session.latest_target_id,
            "latest_result": session.latest_result,
            "agent_behavior": agent_behavior,
            "agent_error": agent_error,
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
        try:
            session = store.load_session(session_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown session: {session_id}") from exc
        try:
            result = agent.run(
                session=session,
                session_dir=store.session_dir(session_id),
                text=payload.text,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        updated = store.apply_agent_result(session_id, result)
        publish_session_update(updated, source="agent_result")
        schedule_memory_rewrite(session_id, result)
        return {
            "session_id": updated.session_id,
            "behavior": result["behavior"],
            "latest_result": updated.latest_result,
            "latest_target_id": updated.latest_target_id,
            "latest_target_crop": updated.latest_target_crop,
            "latest_memory": updated.latest_memory,
        }

    return app
