#!/usr/bin/env python3
from __future__ import annotations

from scripts.run_tracking_perception import (
    DEFAULT_CAMERA_SOURCE,
    _prepare_perception_writer,
    _should_emit_event,
    _should_emit_video_sample,
    main,
    parse_args,
)

__all__ = [
    "DEFAULT_CAMERA_SOURCE",
    "_prepare_perception_writer",
    "_should_emit_event",
    "_should_emit_video_sample",
    "main",
    "parse_args",
]


if __name__ == "__main__":
    raise SystemExit(main())
