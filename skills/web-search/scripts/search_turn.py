from __future__ import annotations

import argparse
import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.infra.config import parse_dotenv
from agent.infra.paths import resolve_project_path
from agent.protocol.payloads import processed_skill_payload, reply_session_result
from agent.state.active import resolve_session_id
from agent.state.session import AgentSession, AgentSessionStore

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


def _default_query(session: AgentSession | None) -> str:
    if session is None:
        return ""
    return session.latest_user_text


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
    request_id: str | None = None,
    request_function: str | None = None,
) -> Dict[str, Any]:
    if error not in (None, ""):
        text = f"当前还不能执行网页搜索：{str(error).strip()}"
        session_result = {
            **reply_session_result(text),
        }
        if request_id not in (None, ""):
            session_result["request_id"] = str(request_id).strip()
        if request_function not in (None, ""):
            session_result["function"] = str(request_function).strip()
        return processed_skill_payload(
            skill_name="web-search",
            session_result=session_result,
            tool="search",
            tool_output={"query": query, "configured": False, "error": str(error).strip()},
            latest_result_patch={"search_query": query, "sources": []},
            reason=str(error).strip(),
        )

    assert tool_output is not None
    reply_text = _compose_reply(query, tool_output)
    session_result = {
        **reply_session_result(reply_text, summary=f"web search for: {query}"),
    }
    if request_id not in (None, ""):
        session_result["request_id"] = str(request_id).strip()
    if request_function not in (None, ""):
        session_result["function"] = str(request_function).strip()
    return processed_skill_payload(
        skill_name="web-search",
        session_result=session_result,
        tool="search",
        tool_output=tool_output,
        latest_result_patch={
            "search_query": query,
            "sources": _compact_sources(list(tool_output.get("results") or [])),
        },
    )


def run_web_search_turn(
    *,
    query: str,
    session_id: str | None,
    state_root: Path,
    env_file: Path,
    max_results: int,
    include_answer: bool,
    bound_session: AgentSession | None = None,
    request_id: str | None = None,
) -> Dict[str, Any]:
    session = bound_session
    if session is None:
        resolved_session_id = resolve_session_id(state_root=state_root, session_id=session_id)
        if resolved_session_id is not None:
            session = AgentSessionStore(state_root=state_root).load(resolved_session_id)
    request_function = None if session is None else str(session.session.get("latest_request_function") or "chat").strip()
    resolved_query = str(query).strip() or _default_query(session)
    if not resolved_query:
        payload = build_web_search_payload(
            query="",
            tool_output=None,
            error="missing search query",
            request_id=request_id,
            request_function=request_function,
        )
    else:
        api_key = _load_tavily_key(env_file)
        if not api_key:
            payload = build_web_search_payload(
                query=resolved_query,
                tool_output=None,
                error="missing TAVILY_API_KEY",
                request_id=request_id,
                request_function=request_function,
            )
        else:
            tool_output = _tavily_search(
                query=resolved_query,
                api_key=api_key,
                max_results=max(1, min(int(max_results), 10)),
                include_answer=bool(include_answer),
            )
            payload = build_web_search_payload(
                query=resolved_query,
                tool_output=tool_output,
                request_id=request_id,
                request_function=request_function,
            )
    return payload


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run one deterministic web search skill turn.")
    parser.add_argument("--query", default="")
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--state-root", default="./.runtime/agent-runtime")
    parser.add_argument("--env-file", default=".ENV")
    parser.add_argument("--max-results", type=int, default=5)
    parser.add_argument("--include-answer", action="store_true")
    args = parser.parse_args(argv)

    payload = run_web_search_turn(
        query=str(args.query),
        session_id=args.session_id,
        state_root=resolve_project_path(args.state_root),
        env_file=resolve_project_path(args.env_file),
        max_results=int(args.max_results),
        include_answer=bool(args.include_answer),
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
