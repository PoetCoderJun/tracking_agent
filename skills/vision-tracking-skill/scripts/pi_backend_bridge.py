#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import pi_agent_adapter as adapter


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch backend context, invoke the PI skill adapter, and post the result.")
    parser.add_argument("--backend-base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--tool", choices=("reply", "init", "track"), required=True)
    parser.add_argument("--arguments-json", default=None)
    parser.add_argument("--arguments-file", default=None)
    parser.add_argument("--env-file", default=".ENV")
    parser.add_argument("--config-path", default=str(adapter.DEFAULT_CONFIG_PATH))
    parser.add_argument("--artifacts-root", default="./runtime/pi-agent")
    parser.add_argument("--skip-rewrite-memory", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rewrite-worker-input-file", default=None, help=argparse.SUPPRESS)
    return parser.parse_args()


def build_session_url(base_url: str, session_id: str, suffix: str) -> str:
    base_session_url = f"{base_url.rstrip('/')}/api/v1/sessions/{session_id}"
    normalized_suffix = suffix.lstrip("/")
    if not normalized_suffix:
        return base_session_url
    return f"{base_session_url}/{normalized_suffix}"


def fetch_json(url: str) -> Dict[str, Any]:
    request = urllib.request.Request(url=url, method="GET")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    request = urllib.request.Request(
        url=url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def backend_result_payload(tool_output: Dict[str, Any]) -> Dict[str, Any]:
    bounding_box_id = tool_output.get("bounding_box_id")
    if bounding_box_id is None:
        bounding_box_id = tool_output.get("target_id")
    payload = {
        "behavior": str(tool_output.get("behavior", "reply")),
        "text": str(tool_output.get("text", "")).strip(),
        "frame_id": tool_output.get("frame_id"),
        "target_id": tool_output.get("target_id"),
        "bounding_box_id": bounding_box_id,
        "found": bool(tool_output.get("found", False)),
        "needs_clarification": bool(tool_output.get("needs_clarification", False)),
        "clarification_question": tool_output.get("clarification_question"),
        "memory": str(tool_output.get("memory", "")).strip(),
        "target_description": str(tool_output.get("target_description", "")).strip(),
        "pending_question": tool_output.get("pending_question"),
        "latest_target_crop": tool_output.get("latest_target_crop"),
    }
    return payload


def backend_memory_update_payload(rewrite_output: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "memory": str(rewrite_output.get("memory", "")).strip(),
        "expected_frame_id": str(rewrite_output.get("frame_id", "")).strip(),
        "expected_target_id": int(rewrite_output["target_id"]),
        "expected_target_crop": rewrite_output.get("crop_path"),
    }


def rewrite_worker_dir(artifacts_root: Path, session_id: str) -> Path:
    path = artifacts_root / session_id / "rewrite_workers"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_rewrite_worker_input(
    *,
    artifacts_root: Path,
    session_id: str,
    rewrite_input: Dict[str, Any],
) -> Path:
    worker_dir = rewrite_worker_dir(artifacts_root, session_id)
    path = worker_dir / f"rewrite_{rewrite_input['frame_id']}_{rewrite_input['target_id']}.json"
    path.write_text(
        json.dumps(rewrite_input, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    return path


def start_rewrite_worker(
    *,
    backend_base_url: str,
    session_id: str,
    env_file: Path,
    config_path: Path,
    artifacts_root: Path,
    rewrite_input_file: Path,
) -> Dict[str, Any]:
    worker_dir = rewrite_worker_dir(artifacts_root, session_id)
    log_file = worker_dir / f"{rewrite_input_file.stem}.log"
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--backend-base-url",
        backend_base_url,
        "--session-id",
        session_id,
        "--tool",
        "track",
        "--env-file",
        str(env_file),
        "--config-path",
        str(config_path),
        "--artifacts-root",
        str(artifacts_root),
        "--skip-rewrite-memory",
        "--rewrite-worker-input-file",
        str(rewrite_input_file),
    ]
    with log_file.open("a", encoding="utf-8") as handle:
        process = subprocess.Popen(
            command,
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return {
        "pid": process.pid,
        "input_file": str(rewrite_input_file),
        "log_file": str(log_file),
    }


def run_rewrite_worker(
    *,
    backend_base_url: str,
    session_id: str,
    rewrite_worker_input_file: Path,
    env_file: Path,
    config_path: Path,
    artifacts_root: Path,
) -> Dict[str, Any]:
    rewrite_input = json.loads(rewrite_worker_input_file.read_text(encoding="utf-8"))
    rewrite_output = adapter.execute_tool(
        tool_name="rewrite_memory",
        context={},
        arguments=rewrite_input,
        env_file=env_file,
        config_path=config_path,
        artifacts_root=artifacts_root,
    )
    memory_update_payload = backend_memory_update_payload(rewrite_output)
    memory_update_url = build_session_url(backend_base_url, session_id, "memory-update")
    memory_update_result = post_json(memory_update_url, memory_update_payload)
    return {
        "session_id": session_id,
        "rewrite_worker_input_file": str(rewrite_worker_input_file),
        "rewrite_output": rewrite_output,
        "memory_update_payload": memory_update_payload,
        "memory_update_result": memory_update_result,
    }


def run_bridge(
    *,
    backend_base_url: str,
    session_id: str,
    tool_name: str,
    arguments: Dict[str, Any],
    env_file: Path,
    config_path: Path,
    artifacts_root: Path,
    skip_rewrite_memory: bool,
    dry_run: bool,
) -> Dict[str, Any]:
    session_url = build_session_url(backend_base_url, session_id, "")
    result_url = build_session_url(backend_base_url, session_id, "agent-result")
    memory_update_url = build_session_url(backend_base_url, session_id, "memory-update")

    raw_session = fetch_json(session_url)
    context = adapter.build_working_context(raw_session)
    tool_output = adapter.execute_tool(
        tool_name=tool_name,
        context=context,
        arguments=arguments,
        env_file=env_file,
        config_path=config_path,
        artifacts_root=artifacts_root,
    )
    payload = backend_result_payload(tool_output)
    posted = None if dry_run else post_json(result_url, payload)
    rewrite_output = None
    rewrite_worker = None
    memory_update_payload = None
    memory_update_result = None
    rewrite_input = tool_output.get("rewrite_memory_input")
    if not skip_rewrite_memory and rewrite_input:
        if not dry_run:
            rewrite_input_file = write_rewrite_worker_input(
                artifacts_root=artifacts_root,
                session_id=session_id,
                rewrite_input=dict(rewrite_input),
            )
            rewrite_worker = start_rewrite_worker(
                backend_base_url=backend_base_url,
                session_id=session_id,
                env_file=env_file,
                config_path=config_path,
                artifacts_root=artifacts_root,
                rewrite_input_file=rewrite_input_file,
            )

    return {
        "session_id": session_id,
        "tool": tool_name,
        "session_url": session_url,
        "result_url": result_url,
        "memory_update_url": memory_update_url,
        "raw_session": raw_session,
        "working_context": context,
        "tool_output": tool_output,
        "rewrite_output": rewrite_output,
        "rewrite_worker": rewrite_worker,
        "posted_result": posted,
        "posted_payload": payload,
        "memory_update_payload": memory_update_payload,
        "memory_update_result": memory_update_result,
        "dry_run": dry_run,
    }


def main() -> int:
    args = parse_args()
    if args.rewrite_worker_input_file:
        payload = run_rewrite_worker(
            backend_base_url=args.backend_base_url,
            session_id=args.session_id,
            rewrite_worker_input_file=Path(args.rewrite_worker_input_file),
            env_file=Path(args.env_file),
            config_path=Path(args.config_path),
            artifacts_root=Path(args.artifacts_root),
        )
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    payload = run_bridge(
        backend_base_url=args.backend_base_url,
        session_id=args.session_id,
        tool_name=args.tool,
        arguments=adapter.load_arguments(args.arguments_json, args.arguments_file),
        env_file=Path(args.env_file),
        config_path=Path(args.config_path),
        artifacts_root=Path(args.artifacts_root),
        skip_rewrite_memory=args.skip_rewrite_memory,
        dry_run=args.dry_run,
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
