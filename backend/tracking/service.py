from __future__ import annotations

import argparse
import subprocess
import sys

from backend.tracking.env import float_env_value, load_tracking_env_values


def parse_args() -> argparse.Namespace:
    bootstrap_parser = argparse.ArgumentParser(add_help=False)
    bootstrap_parser.add_argument("--env-file", default=".ENV")
    bootstrap_args, _ = bootstrap_parser.parse_known_args()
    env_values = load_tracking_env_values(bootstrap_args.env_file)

    parser = argparse.ArgumentParser(
        description="Run the tracking backend service as a thin wrapper around backend.tracking.loop."
    )
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--device-id", default="robot_01")
    parser.add_argument("--state-root", default="./.runtime/agent-runtime")
    parser.add_argument("--env-file", default=bootstrap_args.env_file)
    parser.add_argument("--artifacts-root", default="./.runtime/pi-agent")
    parser.add_argument("--continue-text", default="继续跟踪")
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=float_env_value(env_values, "QUERY_INTERVAL_SECONDS", 3.0),
    )
    parser.add_argument(
        "--recovery-interval-seconds",
        type=float,
        default=float_env_value(env_values, "TRACKING_RECOVERY_INTERVAL_SECONDS", 1.0),
    )
    parser.add_argument(
        "--idle-sleep-seconds",
        type=float,
        default=float_env_value(env_values, "TRACKING_IDLE_SLEEP_SECONDS", 3.0),
    )
    parser.add_argument(
        "--presence-check-seconds",
        type=float,
        default=float_env_value(env_values, "TRACKING_PRESENCE_CHECK_SECONDS", 1.0),
    )
    parser.add_argument("--max-turns", type=int, default=None)
    parser.add_argument("--stop-file", default=None)
    return parser.parse_args()


def _loop_command(args: argparse.Namespace) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "backend.tracking.loop",
        "--device-id",
        str(args.device_id),
        "--state-root",
        str(args.state_root),
        "--env-file",
        str(args.env_file),
        "--artifacts-root",
        str(args.artifacts_root),
        "--continue-text",
        str(args.continue_text),
        "--interval-seconds",
        str(args.interval_seconds),
        "--recovery-interval-seconds",
        str(args.recovery_interval_seconds),
        "--idle-sleep-seconds",
        str(args.idle_sleep_seconds),
        "--presence-check-seconds",
        str(args.presence_check_seconds),
    ]
    if args.session_id not in (None, ""):
        command.extend(["--session-id", str(args.session_id)])
    if args.max_turns is not None:
        command.extend(["--max-turns", str(args.max_turns)])
    if args.stop_file not in (None, ""):
        command.extend(["--stop-file", str(args.stop_file)])
    return command


def main() -> int:
    args = parse_args()
    completed = subprocess.run(_loop_command(args), check=False)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
