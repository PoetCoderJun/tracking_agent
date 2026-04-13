from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Sequence

from agent.project_paths import resolve_project_path
from world.perception.stream import RobotDetection

DEFAULT_SYSTEM1_MODEL = "yolov8n.pt"
DEFAULT_SYSTEM1_TRACKER = "bytetrack.yaml"
DEFAULT_PERSON_CLASS_ID = 0


def load_yolo():
    try:
        from ultralytics import YOLO
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Missing YOLO runtime dependency. Install ultralytics before running the system1 writer."
        ) from exc
    return YOLO


def _tensor_values(value: Any) -> list[Any]:
    if value is None:
        return []
    detach = getattr(value, "detach", None)
    if callable(detach):
        value = detach()
    cpu = getattr(value, "cpu", None)
    if callable(cpu):
        value = cpu()
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        return list(tolist())
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, dict)):
        return list(value)
    return [value]


def extract_person_detections(
    result: Any,
    *,
    person_class_id: int = DEFAULT_PERSON_CLASS_ID,
) -> List[RobotDetection]:
    boxes = getattr(result, "boxes", None)
    if boxes is None:
        return []

    xyxy_values = _tensor_values(getattr(boxes, "xyxy", None))
    cls_values = _tensor_values(getattr(boxes, "cls", None))
    conf_values = _tensor_values(getattr(boxes, "conf", None))
    track_id_values = _tensor_values(getattr(boxes, "id", None))

    detections: List[RobotDetection] = []
    for index, bbox_values in enumerate(xyxy_values):
        cls_value = None if index >= len(cls_values) else cls_values[index]
        if cls_value is not None and int(round(float(cls_value))) != int(person_class_id):
            continue
        if not isinstance(bbox_values, Sequence) or len(bbox_values) != 4:
            continue
        track_id = -1
        if index < len(track_id_values) and track_id_values[index] is not None:
            track_id = int(round(float(track_id_values[index])))
        score = 1.0 if index >= len(conf_values) else float(conf_values[index])
        detections.append(
            RobotDetection(
                track_id=track_id,
                bbox=[int(round(float(value))) for value in bbox_values],
                score=score,
            )
        )
    return detections


def _result_detections_to_payload(detections: List[RobotDetection]) -> List[Dict[str, Any]]:
    return [
        {
            "track_id": None if int(detection.track_id) < 0 else int(detection.track_id),
            "bbox": [int(value) for value in detection.bbox],
            "score": float(detection.score),
            "label": str(detection.label).strip() or "person",
        }
        for detection in detections
    ]


def _track_kwargs(
    *,
    source: object,
    conf: float,
    imgsz: int | None,
    device: str | None,
    tracker: str | None,
    person_class_id: int,
    stream: bool,
) -> Dict[str, object]:
    kwargs: Dict[str, object] = {
        "source": source,
        "conf": conf,
        "persist": True,
        "stream": stream,
        "verbose": False,
        "classes": [person_class_id],
    }
    if imgsz is not None:
        kwargs["imgsz"] = imgsz
    if device not in (None, ""):
        kwargs["device"] = device
    if tracker not in (None, ""):
        kwargs["tracker"] = tracker
    return kwargs


def results_for_video_file(
    *,
    model: object,
    video_path: Path,
    fps: float,
    args: Any,
) -> Iterator[tuple[int, Any]]:
    from world.perception.stream import _load_cv2

    _ = fps
    cv2 = _load_cv2()
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Unable to open video source: {video_path}")

    vid_stride = max(1, int(getattr(args, "vid_stride", 1)))
    frame_number = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok or frame is None:
                break
            frame_number += 1
            if vid_stride > 1 and frame_number % vid_stride != 0:
                continue
            result_batch = model.track(
                **_track_kwargs(
                    source=frame,
                    conf=float(getattr(args, "conf", 0.25)),
                    imgsz=getattr(args, "imgsz", None),
                    device=getattr(args, "device", None),
                    tracker=getattr(args, "tracker", None),
                    person_class_id=int(getattr(args, "person_class_id", DEFAULT_PERSON_CLASS_ID)),
                    stream=False,
                )
            )
            yield frame_number, None if not result_batch else result_batch[0]
    finally:
        capture.release()


@dataclass
class System1Tracker:
    model_path: Path
    tracker: str | None = DEFAULT_SYSTEM1_TRACKER
    device: str | None = None
    conf: float = 0.25
    imgsz: int | None = None
    person_class_id: int = DEFAULT_PERSON_CLASS_ID

    def __post_init__(self) -> None:
        YOLO = load_yolo()
        self._model = YOLO(str(resolve_project_path(self.model_path)))

    def model_info(self) -> Dict[str, Any]:
        return {
            "model_path": str(resolve_project_path(self.model_path)),
            "tracker": None if self.tracker in (None, "") else str(self.tracker),
            "class_filter": ["person"],
            "person_class_id": int(self.person_class_id),
            "conf": float(self.conf),
            "imgsz": None if self.imgsz is None else int(self.imgsz),
            "device": None if self.device in (None, "") else str(self.device),
        }

    def track_detections(
        self,
        *,
        frame_bgr: Any,
    ) -> List[RobotDetection]:
        result_batch = self._model.track(
            **_track_kwargs(
                source=frame_bgr,
                conf=float(self.conf),
                imgsz=self.imgsz,
                device=self.device,
                tracker=self.tracker,
                person_class_id=int(self.person_class_id),
                stream=False,
            )
        )
        result = None if not result_batch else result_batch[0]
        return [] if result is None else extract_person_detections(result, person_class_id=self.person_class_id)

    def track_frame(
        self,
        *,
        frame_id: str,
        timestamp_ms: int,
        image_path: Path,
        frame_bgr: Any | None = None,
    ) -> Dict[str, Any]:
        if frame_bgr is None:
            result_batch = self._model.track(
                **_track_kwargs(
                    source=str(image_path),
                    conf=float(self.conf),
                    imgsz=self.imgsz,
                    device=self.device,
                    tracker=self.tracker,
                    person_class_id=int(self.person_class_id),
                    stream=False,
                )
            )
            result = None if not result_batch else result_batch[0]
            detections = [] if result is None else extract_person_detections(result, person_class_id=self.person_class_id)
        else:
            detections = self.track_detections(frame_bgr=frame_bgr)
        return {
            "frame_id": str(frame_id).strip(),
            "timestamp_ms": int(timestamp_ms),
            "image_path": str(image_path),
            "detections": _result_detections_to_payload(detections),
        }
