from __future__ import annotations

import argparse
import json
from typing import List, Optional

from backend.feishu import run_notify_turn
from backend.project_paths import resolve_project_path


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Write one Feishu notification turn from persisted session state.")
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--state-root", default="./.runtime/agent-runtime")
    parser.add_argument("--title", default=None)
    parser.add_argument("--message", default=None)
    parser.add_argument("--event-type", default="")
    parser.add_argument("--recipient", default=None)
    parser.add_argument("--recipient-type", default=None)
    parser.add_argument("--env-file", default=".ENV")
    parser.add_argument("--artifacts-root", default="./.runtime/pi-agent")
    args = parser.parse_args(argv)

    payload = run_notify_turn(
        session_id=args.session_id,
        state_root=resolve_project_path(args.state_root),
        title=args.title,
        message=args.message,
        event_type=str(args.event_type),
        recipient=args.recipient,
        recipient_type=args.recipient_type,
        env_file=resolve_project_path(args.env_file),
        artifacts_root=resolve_project_path(args.artifacts_root),
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
