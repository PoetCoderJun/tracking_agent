from __future__ import annotations

from pathlib import Path

from world.perception.recorder import PerceptionRecorder


def test_saved_frame_paths_ignores_files_removed_during_scan(tmp_path: Path, monkeypatch) -> None:
    recorder_root = tmp_path / "keyframes"
    sensor_dir = recorder_root / "front_camera"
    sensor_dir.mkdir(parents=True, exist_ok=True)
    kept = sensor_dir / "frame_keep.jpg"
    missing = sensor_dir / "frame_missing.jpg"
    kept.write_bytes(b"keep")
    missing.write_bytes(b"missing")

    original_stat = Path.stat

    def _stat_with_missing(self: Path, *args, **kwargs):
        if self == missing:
            raise FileNotFoundError(self)
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", _stat_with_missing)

    recorder = PerceptionRecorder(recorder_root)

    assert recorder.saved_frame_paths(sensor="front_camera") == [kept]
