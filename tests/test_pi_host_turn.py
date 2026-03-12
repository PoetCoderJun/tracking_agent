from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOST_TURN_PATH = ROOT / "skills" / "vision-tracking-skill" / "scripts" / "pi_host_turn.py"


def _load_host_turn():
    spec = importlib.util.spec_from_file_location("vision_tracking_pi_host_turn", HOST_TURN_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load host-turn module from {HOST_TURN_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_manifest_to_openai_tools_converts_skill_tools() -> None:
    host_turn = _load_host_turn()
    manifest = host_turn.adapter.describe_tools(host_turn.adapter.DEFAULT_TOOLS_PATH)

    tools = host_turn.manifest_to_openai_tools(manifest)

    assert any(tool["function"]["name"] == "reply" for tool in tools)
    assert all(tool["type"] == "function" for tool in tools)


def test_execute_model_selected_tools_runs_track_then_rewrite(tmp_path: Path, monkeypatch) -> None:
    host_turn = _load_host_turn()

    responses = [
        {
            "response_text": "",
            "response_message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_track",
                        "type": "function",
                        "function": {
                            "name": "track",
                            "arguments": "{}",
                        },
                    }
                ],
            },
            "tool_calls": [
                {
                    "id": "call_track",
                    "type": "function",
                    "function": {
                        "name": "track",
                        "arguments": "{}",
                    },
                }
            ],
        },
        {
            "response_text": "",
            "response_message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_rewrite",
                        "type": "function",
                        "function": {
                            "name": "rewrite_memory",
                            "arguments": '{"task":"update","crop_path":"/tmp/crop.jpg","frame_paths":["/tmp/frame.jpg"],"frame_id":"frame_000001","target_id":15}',
                        },
                    }
                ],
            },
            "tool_calls": [
                {
                    "id": "call_rewrite",
                    "type": "function",
                    "function": {
                        "name": "rewrite_memory",
                        "arguments": '{"task":"update","crop_path":"/tmp/crop.jpg","frame_paths":["/tmp/frame.jpg"],"frame_id":"frame_000001","target_id":15}',
                    },
                }
            ],
        },
        {
            "response_text": "本轮处理完成。",
            "response_message": {"role": "assistant", "content": "本轮处理完成。"},
            "tool_calls": [],
        },
    ]

    def fake_call_model_with_tools(**kwargs):
        return responses.pop(0)

    def fake_execute_tool(*, tool_name, context, arguments, env_file, config_path, artifacts_root):
        if tool_name == "track":
            return {
                "behavior": "track",
                "text": "继续跟踪当前目标。",
                "target_id": 15,
                "found": True,
                "needs_clarification": False,
                "clarification_question": None,
                "memory": "",
                "target_description": "黑衣服的人",
                "pending_question": None,
                "latest_target_crop": str(tmp_path / "crop.jpg"),
                "rewrite_memory_input": {
                    "task": "update",
                    "crop_path": str(tmp_path / "crop.jpg"),
                    "frame_paths": [str(tmp_path / "frame.jpg")],
                    "frame_id": "frame_000001",
                    "target_id": 15,
                },
            }
        if tool_name == "rewrite_memory":
            return {
                "task": "update",
                "memory": "更新后的 memory",
                "frame_id": "frame_000001",
                "target_id": 15,
                "crop_path": str(tmp_path / "crop.jpg"),
            }
        raise AssertionError(f"Unexpected tool: {tool_name}")

    monkeypatch.setattr(host_turn, "call_model_with_tools", fake_call_model_with_tools)
    monkeypatch.setattr(host_turn.adapter, "execute_tool", fake_execute_tool)

    result = host_turn.execute_model_selected_tools(
        context={"session_id": "sess_001"},
        messages=[{"role": "system", "content": "sys"}],
        tools=[{"type": "function", "function": {"name": "track"}}],
        env_file=tmp_path / ".ENV",
        tool_config_path=host_turn.adapter.DEFAULT_CONFIG_PATH,
        artifacts_root=tmp_path / "pi-agent",
        settings=type(
            "Settings",
            (),
            {"api_key": "", "base_url": "", "timeout_seconds": 30, "main_model": "main"},
        )(),
        host_config={"limits": {"host_max_tokens": 128, "max_tool_rounds": 4}},
    )

    assert [item["tool_name"] for item in result["executed_tools"]] == ["track", "rewrite_memory"]
    assert result["backend_payload"]["memory"] == "更新后的 memory"
    assert result["backend_payload"]["behavior"] == "track"


def test_run_host_turn_fetches_context_and_posts_result(tmp_path: Path, monkeypatch) -> None:
    host_turn = _load_host_turn()

    monkeypatch.setattr(
        host_turn.bridge,
        "fetch_json",
        lambda url: {
            "session_id": "sess_001",
            "target_description": "黑衣服的人",
            "memory": "",
            "latest_target_id": None,
            "pending_question": None,
            "latest_result": None,
            "conversation_history": [{"role": "user", "text": "跟踪黑衣服的人"}],
            "frames": [],
        },
    )
    monkeypatch.setattr(host_turn, "load_agent_config", lambda path: {"prompts": {"host_system_prompt": "{latest_user_text}"}, "limits": {"host_max_tokens": 64, "max_tool_rounds": 2}})
    monkeypatch.setattr(
        host_turn.adapter,
        "describe_tools",
        lambda path: {
            "tools": [
                {
                    "name": "reply",
                    "description": "reply",
                    "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
                }
            ],
            "tooling_notes": [],
        },
    )
    monkeypatch.setattr(
        host_turn,
        "load_settings",
        lambda path: type("Settings", (), {"api_key": "", "base_url": "", "timeout_seconds": 30, "main_model": "main"})(),
    )
    monkeypatch.setattr(
        host_turn,
        "execute_model_selected_tools",
        lambda **kwargs: {
            "messages": [],
            "executed_tools": [{"tool_name": "reply"}],
            "backend_payload": {
                "behavior": "reply",
                "text": "请再具体描述一下目标。",
                "target_id": None,
                "found": False,
                "needs_clarification": True,
                "clarification_question": "请再具体描述一下目标。",
                "memory": "",
                "target_description": "",
                "pending_question": "请再具体描述一下目标。",
                "latest_target_crop": None,
            },
            "final_response_text": "done",
        },
    )
    posted: list[dict[str, object]] = []
    monkeypatch.setattr(
        host_turn.bridge,
        "post_json",
        lambda url, payload: posted.append({"url": url, "payload": payload}) or {"ok": True},
    )

    result = host_turn.run_host_turn(
        backend_base_url="http://127.0.0.1:8001",
        session_id="sess_001",
        env_file=tmp_path / ".ENV",
        tool_config_path=host_turn.adapter.DEFAULT_CONFIG_PATH,
        host_config_path=host_turn.DEFAULT_HOST_CONFIG_PATH,
        tools_path=host_turn.adapter.DEFAULT_TOOLS_PATH,
        artifacts_root=tmp_path / "pi-agent",
        dry_run=False,
    )

    assert result["executed_tools"][0]["tool_name"] == "reply"
    assert posted[0]["url"].endswith("/api/v1/sessions/sess_001/agent-result")
