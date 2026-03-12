from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Optional, Protocol, Sequence

from tracking_agent.bbox_visualization import save_bbox_visualization
from tracking_agent.output_validator import validate_locate_result
from tracking_agent.core.session_store import SessionStore
from tracking_agent.target_crop import save_target_crop


class TrackingBackend(Protocol):
    def bootstrap_target(
        self,
        target_description: str,
        frame_paths: Sequence[Path],
    ) -> Dict[str, Any]:
        ...

    def initialize_memory(
        self,
        frame_paths: Sequence[Path],
        target_crop_path: Path,
        bootstrap_description: Optional[str] = None,
    ) -> str:
        ...

    def locate_target(
        self,
        memory_markdown: str,
        frame_paths: Sequence[Path],
        reference_frame_paths: Optional[Sequence[Path]] = None,
        human_guidance: Optional[str] = None,
        edge_hint: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        ...

    def rewrite_memory(
        self,
        previous_memory: str,
        locate_result: Dict[str, Any],
        frame_paths: Sequence[Path],
        reference_frame_paths: Optional[Sequence[Path]] = None,
    ) -> str:
        ...

    def answer_chat(
        self,
        memory_markdown: str,
        question: str,
        frame_paths: Sequence[Path],
        reference_frame_paths: Optional[Sequence[Path]] = None,
    ) -> str:
        ...


class PiAgentCore:
    def __init__(self, store: SessionStore, backend: TrackingBackend):
        self._store = store
        self._backend = backend

    def initialize_target(
        self,
        session_id: str,
        target_description: str,
        frame_paths: Sequence[Path],
    ) -> Dict[str, Any]:
        bootstrap_result = self._locate_bootstrap_target(
            target_description=target_description,
            frame_paths=frame_paths,
        )
        if not bootstrap_result["found"] or bootstrap_result["bbox"] is None:
            session = self._store.create_or_reset_session(
                session_id=session_id,
                target_description=target_description,
                initial_memory="",
            )
            self._store.write_latest_result(session_id, bootstrap_result)
            session = self._store.update_status(
                session_id=session_id,
                status="clarifying",
                pending_clarification_question=bootstrap_result["clarification_question"],
            )
            visualization_path = self._write_frame_visualization(
                session_id=session_id,
                source_frame=frame_paths[-1],
                result=bootstrap_result,
                stage="bootstrap",
            )
            return {
                "session": asdict(session),
                "memory": self._store.read_memory(session_id),
                "bootstrap_result": bootstrap_result,
                "frame_visualization_path": str(visualization_path),
            }

        crop_path = self._write_target_crop(
            session_id=session_id,
            source_frame=frame_paths[-1],
            bbox=bootstrap_result["bbox"],
        )
        initial_memory = self._backend.initialize_memory(
            frame_paths=frame_paths,
            target_crop_path=crop_path,
            bootstrap_description=target_description,
        )
        session = self._store.create_or_reset_session(
            session_id=session_id,
            target_description=target_description,
            initial_memory=initial_memory,
        )
        self._store.add_reference_crop(session_id, crop_path)
        self._store.set_latest_confirmed_frame_path(session_id, frame_paths[-1])
        self._store.write_latest_result(session_id, bootstrap_result)
        session = self._store.load_session(session_id)
        visualization_path = self._write_frame_visualization(
            session_id=session_id,
            source_frame=frame_paths[-1],
            result=bootstrap_result,
            stage="bootstrap",
        )
        return {
            "session": asdict(session),
            "memory": self._store.read_memory(session_id),
            "bootstrap_result": bootstrap_result,
            "frame_visualization_path": str(visualization_path),
        }

    def replace_target(
        self,
        session_id: str,
        target_description: str,
        frame_paths: Sequence[Path],
    ) -> Dict[str, Any]:
        return self.initialize_target(
            session_id=session_id,
            target_description=target_description,
            frame_paths=frame_paths,
        )

    def add_clarification(self, session_id: str, note: str) -> Dict[str, Any]:
        session = self._store.add_clarification_note(session_id, note)
        return {"session": asdict(session)}

    def run_tracking_step(
        self,
        session_id: str,
        frame_paths: Sequence[Path],
        recovery_frame_paths: Optional[Sequence[Path]] = None,
        edge_hint: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        session = self._store.load_session(session_id)
        memory_markdown = self._store.read_memory(session_id)
        human_guidance = "\n".join(session.clarification_notes[-3:]) or None
        reference_frame_paths = self._latest_reference_frame_paths(session)

        locate_result = self._locate_once(
            memory_markdown=memory_markdown,
            frame_paths=frame_paths,
            reference_frame_paths=reference_frame_paths,
            human_guidance=human_guidance,
            edge_hint=edge_hint,
        )
        used_recovery_context = False
        locate_context = frame_paths

        if (
            not locate_result["found"]
            and not locate_result["needs_clarification"]
            and recovery_frame_paths
            and self._paths_differ(frame_paths, recovery_frame_paths)
        ):
            locate_result = self._locate_once(
                memory_markdown=memory_markdown,
                frame_paths=recovery_frame_paths,
                reference_frame_paths=reference_frame_paths,
                human_guidance=human_guidance,
                edge_hint=edge_hint,
            )
            used_recovery_context = True
            locate_context = recovery_frame_paths

        rewrite_context = self._select_rewrite_context(
            locate_result=locate_result,
            frame_paths=frame_paths,
            recovery_frame_paths=recovery_frame_paths,
            locate_context=locate_context,
        )

        crop_updated = False
        if locate_result["found"] and locate_result["bbox"] is not None:
            crop_path = self._write_target_crop(
                session_id=session_id,
                source_frame=locate_context[-1],
                bbox=locate_result["bbox"],
            )
            session = self._store.add_reference_crop(session_id, crop_path)
            session = self._store.set_latest_confirmed_frame_path(
                session_id=session_id,
                frame_path=locate_context[-1],
            )
            crop_updated = True

        memory_updated = self._should_rewrite_memory(locate_result)
        if memory_updated:
            updated_memory = self._backend.rewrite_memory(
                previous_memory=memory_markdown,
                locate_result=locate_result,
                frame_paths=rewrite_context,
                reference_frame_paths=self._latest_reference_frame_paths(session),
            )
            self._store.write_memory(session_id, updated_memory)
        session = self._store.write_latest_result(session_id, locate_result)

        if locate_result["needs_clarification"]:
            status = "clarifying"
        elif locate_result["found"]:
            status = "tracked"
        else:
            status = "missing"

        session = self._store.update_status(
            session_id=session_id,
            status=status,
            pending_clarification_question=locate_result["clarification_question"],
        )
        visualization_path = self._write_frame_visualization(
            session_id=session_id,
            source_frame=locate_context[-1],
            result=locate_result,
            stage=status,
        )
        self._store.append_event(
            session_id,
            "tracking_step",
            {
                "status": status,
                "found": locate_result["found"],
                "confidence": locate_result["confidence"],
                "memory_updated": memory_updated,
                "used_recovery_context": used_recovery_context,
                "crop_updated": crop_updated,
                "frame_visualization_path": str(visualization_path),
            },
        )

        return {
            "session": asdict(session),
            "locate_result": locate_result,
            "memory": self._store.read_memory(session_id),
            "memory_updated": memory_updated,
            "used_recovery_context": used_recovery_context,
            "crop_updated": crop_updated,
            "frame_visualization_path": str(visualization_path),
        }

    def answer_chat(
        self,
        session_id: str,
        question: str,
        frame_paths: Sequence[Path],
    ) -> Dict[str, Any]:
        session = self._store.load_session(session_id)
        memory_markdown = self._store.read_memory(session_id)
        answer = self._backend.answer_chat(
            memory_markdown=memory_markdown,
            question=question,
            frame_paths=frame_paths,
            reference_frame_paths=self._latest_reference_frame_paths(session),
        )
        self._store.append_event(
            session_id,
            "chat",
            {"question": question, "answer": answer},
        )
        return {
            "session": asdict(self._store.load_session(session_id)),
            "answer": answer,
        }

    def get_status(self, session_id: str) -> Dict[str, Any]:
        session = self._store.load_session(session_id)
        return {
            "session": asdict(session),
            "memory": self._store.read_memory(session_id),
            "events": self._store.read_events(session_id),
        }

    def _locate_once(
        self,
        memory_markdown: str,
        frame_paths: Sequence[Path],
        reference_frame_paths: Optional[Sequence[Path]],
        human_guidance: Optional[str],
        edge_hint: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return validate_locate_result(
            self._backend.locate_target(
                memory_markdown=memory_markdown,
                frame_paths=frame_paths,
                reference_frame_paths=reference_frame_paths,
                human_guidance=human_guidance,
                edge_hint=edge_hint,
            )
        )

    def _locate_bootstrap_target(
        self,
        target_description: str,
        frame_paths: Sequence[Path],
    ) -> Dict[str, Any]:
        return validate_locate_result(
            self._backend.bootstrap_target(
                target_description=target_description,
                frame_paths=frame_paths,
            )
        )

    def _should_rewrite_memory(self, locate_result: Dict[str, Any]) -> bool:
        return bool(locate_result["found"])

    def _paths_differ(
        self,
        left: Sequence[Path],
        right: Sequence[Path],
    ) -> bool:
        return [str(path) for path in left] != [str(path) for path in right]

    def _select_rewrite_context(
        self,
        locate_result: Dict[str, Any],
        frame_paths: Sequence[Path],
        recovery_frame_paths: Optional[Sequence[Path]],
        locate_context: Sequence[Path],
    ) -> Sequence[Path]:
        if (
            not locate_result["found"]
            and not locate_result["needs_clarification"]
            and recovery_frame_paths
            and self._paths_differ(frame_paths, recovery_frame_paths)
        ):
            return recovery_frame_paths
        return locate_context

    def _write_target_crop(
        self,
        session_id: str,
        source_frame: Path,
        bbox: Sequence[int],
    ) -> Path:
        session_dir = self._store.session_dir(session_id)
        crops_dir = session_dir / "reference_crops"
        crops_dir.mkdir(parents=True, exist_ok=True)
        next_index = len(list(crops_dir.glob("target_crop_*.jpg")))
        crop_path = crops_dir / f"target_crop_{next_index:04d}.jpg"
        return save_target_crop(source_frame, bbox, crop_path)

    def _latest_reference_frame_paths(self, session) -> Optional[Sequence[Path]]:
        if session.latest_confirmed_frame_path:
            return [Path(session.latest_confirmed_frame_path)]
        return None

    def _write_frame_visualization(
        self,
        session_id: str,
        source_frame: Path,
        result: Dict[str, Any],
        stage: str,
    ) -> Path:
        session_dir = self._store.session_dir(session_id)
        visuals_dir = session_dir / "bbox_visualizations"
        visuals_dir.mkdir(parents=True, exist_ok=True)
        next_index = len(list(visuals_dir.glob("step_*.jpg")))
        output_path = visuals_dir / f"step_{next_index:04d}_{stage}_{source_frame.stem}.jpg"
        confidence = float(result.get("confidence", 0.0))
        label = f"{stage.upper()} {confidence:.2f}"
        return save_bbox_visualization(
            image_path=source_frame,
            output_path=output_path,
            bbox=result.get("bbox"),
            label=label,
        )
