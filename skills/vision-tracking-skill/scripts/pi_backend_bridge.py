#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
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
    return parser.parse_args()


def build_session_url(base_url: str, session_id: str, suffix: str) -> str:
    return f"{base_url.rstrip('/')}/api/v1/sessions/{session_id}/{suffix.lstrip('/')}"


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


def maybe_apply_memory_rewrite(
    *,
    tool_output: Dict[str, Any],
    env_file: Path,
    config_path: Path,
    artifacts_root: Path,
    skip_rewrite_memory: bool,
) -> Optional[Dict[str, Any]]:
    rewrite_input = tool_output.get("rewrite_memory_input")
    if skip_rewrite_memory or not rewrite_input:
        return None
    rewrite_output = adapter.execute_tool(
        tool_name="rewrite_memory",
        context={},
        arguments=dict(rewrite_input),
        env_file=env_file,
        config_path=config_path,
        artifacts_root=artifacts_root,
    )
    tool_output["memory"] = rewrite_output["memory"]
    return rewrite_output


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
    context_url = build_session_url(backend_base_url, session_id, "agent-context")
    result_url = build_session_url(backend_base_url, session_id, "agent-result")

    context = fetch_json(context_url)
    tool_output = adapter.execute_tool(
        tool_name=tool_name,
        context=context,
        arguments=arguments,
        env_file=env_file,
        config_path=config_path,
        artifacts_root=artifacts_root,
    )
    rewrite_output = maybe_apply_memory_rewrite(
        tool_output=tool_output,
        env_file=env_file,
        config_path=config_path,
        artifacts_root=artifacts_root,
        skip_rewrite_memory=skip_rewrite_memory,
    )
    payload = backend_result_payload(tool_output)
    posted = None if dry_run else post_json(result_url, payload)

    return {
        "session_id": session_id,
        "tool": tool_name,
        "context_url": context_url,
        "result_url": result_url,
        "tool_output": tool_output,
        "rewrite_output": rewrite_output,
        "posted_result": posted,
        "posted_payload": payload,
        "dry_run": dry_run,
    }


def main() -> int:
    args = parse_args()
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
