from __future__ import annotations

import argparse
import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.config import parse_dotenv
from backend.persistence import resolve_session_id
from backend.project_paths import resolve_project_path
from backend.runtime_apply import apply_processed_payload
from backend.runtime_session import AgentSessionStore
from backend.skill_payload import processed_skill_payload, reply_session_result

TAVILY_URL = "https://api.tavily.com/search"


def _load_tavily_key(env_file: Optional[Path]) -> Optional[str]:
    direct = str(os.environ.get("TAVILY_API_KEY", "")).strip()
    if direct:
        return direct
    if env_file is None:
        return None
    values = parse_dotenv(env_file)
    configured = str(values.get("TAVILY_API_KEY", "")).strip()
    return configured or None


def _default_query(
    *,
    state_root: Path,
    session_id: str | None,
    frame_buffer_size: int,
) -> str:
    resolved_session_id = resolve_session_id(state_root=state_root, session_id=session_id)
    if resolved_session_id is None:
        return ""
    session = AgentSessionStore(
        state_root=state_root,
        frame_buffer_size=frame_buffer_size,
    ).load(resolved_session_id)
    history = list(session.session.get("conversation_history") or [])
    for entry in reversed(history):
        if str(entry.get("role", "")).strip() != "user":
            continue
        text = str(entry.get("text", "")).strip()
        if text:
            return text
    return ""


def _tavily_search(
    *,
    query: str,
    api_key: str,
    max_results: int,
    include_answer: bool,
) -> Dict[str, Any]:
    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": max_results,
        "search_depth": "basic",
        "include_answer": bool(include_answer),
        "include_images": False,
        "include_raw_content": False,
    }
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        TAVILY_URL,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8", errors="replace")
    parsed = json.loads(body)
    results: List[Dict[str, Any]] = []
    for item in list(parsed.get("results") or [])[:max_results]:
        results.append(
            {
                "title": item.get("title"),
                "url": item.get("url"),
                "snippet": item.get("content"),
            }
        )
    output: Dict[str, Any] = {
        "query": query,
        "results": results,
    }
    answer = parsed.get("answer")
    if include_answer and answer not in (None, ""):
        output["answer"] = answer
    return output


def _compact_sources(results: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    sources: List[Dict[str, str]] = []
    for item in results[:5]:
        title = str(item.get("title", "")).strip()
        url = str(item.get("url", "")).strip()
        if not title and not url:
            continue
        sources.append({"title": title, "url": url})
    return sources


def _compose_reply(query: str, tool_output: Dict[str, Any]) -> str:
    answer = str(tool_output.get("answer", "")).strip()
    if answer:
        sources = _compact_sources(list(tool_output.get("results") or []))
        if not sources:
            return answer
        source_lines = "\n".join(
            f"- {source['title'] or source['url']}: {source['url']}"
            for source in sources[:3]
        )
        return f"{answer}\n\n来源：\n{source_lines}"

    result_lines: List[str] = []
    for item in list(tool_output.get("results") or [])[:3]:
        title = str(item.get("title", "")).strip() or "未命名结果"
        url = str(item.get("url", "")).strip()
        snippet = re.sub(r"\s+", " ", str(item.get("snippet", "")).strip())
        line = f"- {title}"
        if url:
            line += f": {url}"
        if snippet:
            line += f" ({snippet[:140]})"
        result_lines.append(line)
    if result_lines:
        return f"我为“{query}”找到了这些相关结果：\n" + "\n".join(result_lines)
    return f"我没有为“{query}”找到可靠的网页结果。"


def build_web_search_payload(
    *,
    query: str,
    tool_output: Optional[Dict[str, Any]],
    error: Optional[str] = None,
) -> Dict[str, Any]:
    if error not in (None, ""):
        text = f"当前还不能执行网页搜索：{str(error).strip()}"
        return processed_skill_payload(
            skill_name="web_search",
            session_result=reply_session_result(text),
            tool="search",
            tool_output={"query": query, "configured": False, "error": str(error).strip()},
            latest_result_patch={"search_query": query, "sources": []},
            reason=str(error).strip(),
        )

    assert tool_output is not None
    reply_text = _compose_reply(query, tool_output)
    return processed_skill_payload(
        skill_name="web_search",
        session_result=reply_session_result(reply_text, summary=f"web search for: {query}"),
        tool="search",
        tool_output=tool_output,
        latest_result_patch={
            "search_query": query,
            "sources": _compact_sources(list(tool_output.get("results") or [])),
        },
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run one deterministic web search skill turn.")
    parser.add_argument("--query", default="")
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--state-root", default="./.runtime/agent-runtime")
    parser.add_argument("--frame-buffer-size", type=int, default=3)
    parser.add_argument("--env-file", default=".ENV")
    parser.add_argument("--max-results", type=int, default=5)
    parser.add_argument("--include-answer", action="store_true")
    args = parser.parse_args(argv)

    state_root = resolve_project_path(args.state_root)
    resolved_session_id = resolve_session_id(state_root=state_root, session_id=args.session_id)
    query = str(args.query).strip() or _default_query(
        state_root=state_root,
        session_id=resolved_session_id,
        frame_buffer_size=int(args.frame_buffer_size),
    )
    if not query:
        payload = build_web_search_payload(
            query="",
            tool_output=None,
            error="missing search query",
        )
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    api_key = _load_tavily_key(resolve_project_path(args.env_file))
    if not api_key:
        payload = build_web_search_payload(
            query=query,
            tool_output=None,
            error="missing TAVILY_API_KEY",
        )
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    tool_output = _tavily_search(
        query=query,
        api_key=api_key,
        max_results=max(1, min(int(args.max_results), 10)),
        include_answer=bool(args.include_answer),
    )
    payload = build_web_search_payload(
        query=query,
        tool_output=tool_output,
    )
    if resolved_session_id is not None:
        payload = apply_processed_payload(
            sessions=AgentSessionStore(state_root=state_root, frame_buffer_size=int(args.frame_buffer_size)),
            session_id=resolved_session_id,
            pi_payload=payload,
            env_file=resolve_project_path(args.env_file),
        )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
