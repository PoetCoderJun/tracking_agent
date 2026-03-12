#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import pi_agent_adapter as adapter
import pi_backend_bridge as bridge
from tracking_agent.config import load_settings

from agent_common import call_model_with_tools, load_agent_config

SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HOST_CONFIG_PATH = SKILL_ROOT / "references" / "pi-host-agent-config.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one PI host-agent turn with model-selected skill tools.")
    parser.add_argument("--backend-base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--env-file", default=".ENV")
    parser.add_argument("--tool-config-path", default=str(adapter.DEFAULT_CONFIG_PATH))
    parser.add_argument("--host-config-path", default=str(DEFAULT_HOST_CONFIG_PATH))
    parser.add_argument("--tools-path", default=str(adapter.DEFAULT_TOOLS_PATH))
    parser.add_argument("--artifacts-root", default="./runtime/pi-agent")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def latest_user_text(context: Dict[str, Any]) -> str:
    history = context.get("conversation_history", [])
    for entry in reversed(history):
        if str(entry.get("role", "")) == "user":
            return str(entry.get("text", "")).strip()
    return ""


def build_host_prompt(context: Dict[str, Any], host_config: Dict[str, Any], tool_manifest: Dict[str, Any]) -> str:
    prompt = str(host_config["prompts"]["host_system_prompt"]).format(
        target_description=context.get("target_description") or "无",
        latest_target_id=context.get("latest_target_id"),
        memory=context.get("memory") or "无",
        pending_question=context.get("pending_question") or "无",
        latest_result_summary=adapter.latest_result_summary(context),
        recent_dialogue=adapter.recent_dialogue(context),
        latest_user_text=latest_user_text(context) or "(空输入)",
    )
    notes = tool_manifest.get("tooling_notes", [])
    if not notes:
        return prompt
    note_block = "\n".join(f"- {note}" for note in notes)
    return f"{prompt}\n\n工具补充说明：\n{note_block}"


def build_initial_messages(context: Dict[str, Any], host_config: Dict[str, Any], tool_manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        {"role": "system", "content": build_host_prompt(context, host_config, tool_manifest)},
        {
            "role": "user",
            "content": "请根据当前会话选择并调用必要工具来推进这一轮 tracking 对话。只有在完成必要工具调用后才停止。",
        },
    ]


def manifest_to_openai_tools(tool_manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    tools: List[Dict[str, Any]] = []
    for tool in tool_manifest.get("tools", []):
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": str(tool["name"]),
                    "description": str(tool.get("description", "")),
                    "parameters": tool.get("input_schema", {"type": "object", "properties": {}, "additionalProperties": False}),
                },
            }
        )
    return tools


def parse_tool_arguments(raw_arguments: Any) -> Dict[str, Any]:
    if raw_arguments in (None, "", {}):
        return {}
    if isinstance(raw_arguments, dict):
        return raw_arguments
    return json.loads(str(raw_arguments))


def assistant_message_from_response(response: Dict[str, Any]) -> Dict[str, Any]:
    message = dict(response.get("response_message") or {})
    assistant_message: Dict[str, Any] = {"role": "assistant"}
    content = message.get("content")
    if content not in (None, ""):
        assistant_message["content"] = content
    elif response.get("response_text"):
        assistant_message["content"] = response["response_text"]
    tool_calls = response.get("tool_calls") or []
    if tool_calls:
        assistant_message["tool_calls"] = tool_calls
    return assistant_message


def execute_model_selected_tools(
    *,
    context: Dict[str, Any],
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    env_file: Path,
    tool_config_path: Path,
    artifacts_root: Path,
    settings: Any,
    host_config: Dict[str, Any],
) -> Dict[str, Any]:
    max_rounds = int(host_config["limits"]["max_tool_rounds"])
    last_backend_payload: Optional[Dict[str, Any]] = None
    executed_tools: List[Dict[str, Any]] = []
    final_response_text = ""

    for _ in range(max_rounds):
        response = call_model_with_tools(
            api_key=settings.api_key,
            base_url=settings.base_url,
            timeout_seconds=settings.timeout_seconds,
            model=settings.main_model,
            messages=messages,
            tools=tools,
            max_tokens=int(host_config["limits"]["host_max_tokens"]),
            tool_choice="auto",
            parallel_tool_calls=False,
        )
        final_response_text = str(response.get("response_text", "")).strip()
        assistant_message = assistant_message_from_response(response)
        messages.append(assistant_message)
        tool_calls = response.get("tool_calls") or []
        if not tool_calls:
            break

        for tool_call in tool_calls:
            function_payload = tool_call.get("function") or {}
            tool_name = str(function_payload.get("name", "")).strip()
            tool_arguments = parse_tool_arguments(function_payload.get("arguments"))
            tool_output = adapter.execute_tool(
                tool_name=tool_name,
                context=context,
                arguments=tool_arguments,
                env_file=env_file,
                config_path=tool_config_path,
                artifacts_root=artifacts_root,
            )
            if tool_name == "rewrite_memory":
                if last_backend_payload is None:
                    raise RuntimeError("rewrite_memory was selected before any reply/init/track result existed")
                last_backend_payload["memory"] = str(tool_output["memory"]).strip()
            else:
                last_backend_payload = bridge.backend_result_payload(tool_output)
            executed_tools.append(
                {
                    "tool_name": tool_name,
                    "arguments": tool_arguments,
                    "output": tool_output,
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": str(tool_call.get("id", "")),
                    "content": json.dumps(tool_output, ensure_ascii=False),
                }
            )

    if last_backend_payload is None:
        raise RuntimeError("Host turn finished without producing a backend agent-result payload")
    if not last_backend_payload.get("text") and final_response_text:
        last_backend_payload["text"] = final_response_text

    return {
        "messages": messages,
        "executed_tools": executed_tools,
        "backend_payload": last_backend_payload,
        "final_response_text": final_response_text,
    }


def run_host_turn(
    *,
    backend_base_url: str,
    session_id: str,
    env_file: Path,
    tool_config_path: Path,
    host_config_path: Path,
    tools_path: Path,
    artifacts_root: Path,
    dry_run: bool,
) -> Dict[str, Any]:
    context_url = bridge.build_session_url(backend_base_url, session_id, "agent-context")
    result_url = bridge.build_session_url(backend_base_url, session_id, "agent-result")
    context = bridge.fetch_json(context_url)
    tool_manifest = adapter.describe_tools(tools_path)
    host_config = load_agent_config(host_config_path)
    settings = load_settings(env_file)
    messages = build_initial_messages(context, host_config, tool_manifest)
    tools = manifest_to_openai_tools(tool_manifest)

    execution = execute_model_selected_tools(
        context=context,
        messages=messages,
        tools=tools,
        env_file=env_file,
        tool_config_path=tool_config_path,
        artifacts_root=artifacts_root,
        settings=settings,
        host_config=host_config,
    )
    posted_result = None if dry_run else bridge.post_json(result_url, execution["backend_payload"])

    return {
        "session_id": session_id,
        "context_url": context_url,
        "result_url": result_url,
        "tool_manifest_path": str(tools_path),
        "executed_tools": execution["executed_tools"],
        "posted_payload": execution["backend_payload"],
        "posted_result": posted_result,
        "final_response_text": execution["final_response_text"],
        "dry_run": dry_run,
    }


def main() -> int:
    args = parse_args()
    payload = run_host_turn(
        backend_base_url=args.backend_base_url,
        session_id=args.session_id,
        env_file=Path(args.env_file),
        tool_config_path=Path(args.tool_config_path),
        host_config_path=Path(args.host_config_path),
        tools_path=Path(args.tools_path),
        artifacts_root=Path(args.artifacts_root),
        dry_run=args.dry_run,
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
