#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.tracking.loop import (
    _bound_status_signature,
    _has_active_target,
    _next_dispatch_deadline,
    _non_target_track_ids,
    _should_request_track_for_frame,
    _should_schedule_rewrite,
    _stream_completed,
    _track_id_present_in_frame,
    _waiting_for_user,
    main,
    parse_args,
)


if __name__ == "__main__":
    raise SystemExit(main())
