from __future__ import annotations

import shutil
from collections import defaultdict, deque
from pathlib import Path
from typing import Deque, DefaultDict, Optional

from world.perception.stream import save_frame_image


class PerceptionRecorder:
    def __init__(
        self,
        root: Path,
        *,
        save_frame_every_seconds: float = 1.0,
        retention_seconds: float = 10.0,
    ):
        if save_frame_every_seconds <= 0:
            raise ValueError("save_frame_every_seconds must be positive")
        if retention_seconds <= 0:
            raise ValueError("retention_seconds must be positive")
        self._root = root
        self._save_frame_every_ms = round(float(save_frame_every_seconds) * 1000)
        self._max_saved_frames = max(1, int(float(retention_seconds) / float(save_frame_every_seconds)))
        self._last_saved_at_ms: dict[str, int] = {}
        self._saved_paths: DefaultDict[str, Deque[Path]] = defaultdict(deque)
        self._root.mkdir(parents=True, exist_ok=True)
        self._load_existing_history()

    def maybe_save_camera_frame(
        self,
        *,
        sensor: str,
        frame_id: str,
        ts_ms: int,
        frame_bgr,
    ) -> Optional[Path]:
        if not self._should_save(sensor=sensor, ts_ms=ts_ms):
            return None
        output_path = self._frame_path(sensor=sensor, frame_id=frame_id)
        save_frame_image(frame_bgr, output_path)
        self._last_saved_at_ms[sensor] = ts_ms
        self._remember_saved_path(sensor=sensor, output_path=output_path)
        return output_path

    def save_frame_reference(
        self,
        *,
        sensor: str,
        frame_id: str,
        ts_ms: int,
        source_path: Path,
        force: bool = False,
    ) -> Optional[Path]:
        if not force and not self._should_save(sensor=sensor, ts_ms=ts_ms):
            return None
        output_path = self._frame_path(sensor=sensor, frame_id=frame_id, suffix=source_path.suffix)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if source_path.resolve() != output_path.resolve():
            shutil.copyfile(source_path, output_path)
        self._last_saved_at_ms[sensor] = ts_ms
        self._remember_saved_path(sensor=sensor, output_path=output_path)
        return output_path

    def saved_frame_paths(self, *, sensor: str) -> list[Path]:
        sensor_dir = self._root / sensor
        if not sensor_dir.exists():
            return []
        ordered_paths: list[tuple[int, Path]] = []
        for path in sensor_dir.iterdir():
            try:
                if not path.is_file():
                    continue
                mtime_ns = path.stat().st_mtime_ns
            except FileNotFoundError:
                continue
            ordered_paths.append((mtime_ns, path))
        ordered_paths.sort(key=lambda item: item[0])
        return [path for _, path in ordered_paths]

    def clear(self) -> None:
        for sensor_paths in self._saved_paths.values():
            sensor_paths.clear()
        self._saved_paths.clear()
        self._last_saved_at_ms.clear()

        if not self._root.exists():
            return
        for path in self._root.rglob("*"):
            if path.is_file():
                path.unlink()

    def _should_save(self, *, sensor: str, ts_ms: int) -> bool:
        last_saved_at_ms = self._last_saved_at_ms.get(sensor)
        if last_saved_at_ms is None:
            return True
        return ts_ms - last_saved_at_ms >= self._save_frame_every_ms

    def _frame_path(self, *, sensor: str, frame_id: str, suffix: str = ".jpg") -> Path:
        return self._root / sensor / f"{frame_id}{suffix or '.jpg'}"

    def _remember_saved_path(self, *, sensor: str, output_path: Path) -> None:
        paths = self._saved_paths[sensor]
        paths.append(output_path)
        while len(paths) > self._max_saved_frames:
            expired_path = paths.popleft()
            try:
                expired_path.unlink()
            except FileNotFoundError:
                continue

    def _load_existing_history(self) -> None:
        for sensor_dir in sorted(path for path in self._root.iterdir() if path.is_dir()):
            paths = self._saved_paths[sensor_dir.name]
            for path in self.saved_frame_paths(sensor=sensor_dir.name):
                paths.append(path)
            while len(paths) > self._max_saved_frames:
                expired_path = paths.popleft()
                try:
                    expired_path.unlink()
                except FileNotFoundError:
                    continue
