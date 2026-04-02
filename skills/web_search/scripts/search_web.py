#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from typing import Any, Callable, Dict, List
from urllib.parse import quote_plus
from urllib.request import Request, urlopen


DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_RESULTS = 5
DUCKDUCKGO_API = "https://api.duckduckgo.com/?q={query}&format=json&no_redirect=1&no_html=1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search the web via DuckDuckGo instant answer API.")
    parser.add_argument("--query", required=True)
    parser.add_argument("--max-results", type=int, default=DEFAULT_MAX_RESULTS)
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _result_items(payload: Dict[str, Any], *, max_results: int) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []

    def append_item(text: Any, url: Any) -> None:
        snippet = str(text or "").strip()
        href = str(url or "").strip()
        if not snippet or not href:
            return
        items.append({"title": snippet, "text": snippet, "url": href})

    append_item(payload.get("AbstractText"), payload.get("AbstractURL"))
    for item in list(payload.get("Results") or []):
        if not isinstance(item, dict):
            continue
        append_item(item.get("Text"), item.get("FirstURL"))
    for item in list(payload.get("RelatedTopics") or []):
        if len(items) >= max_results:
            break
        if isinstance(item, dict) and "Topics" in item:
            for nested in list(item.get("Topics") or []):
                if len(items) >= max_results:
                    break
                if isinstance(nested, dict):
                    append_item(nested.get("Text"), nested.get("FirstURL"))
            continue
        if isinstance(item, dict):
            append_item(item.get("Text"), item.get("FirstURL"))

    deduped: List[Dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        key = item["url"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) >= max_results:
            break
    return deduped


def search_web(
    *,
    query: str,
    max_results: int = DEFAULT_MAX_RESULTS,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    fetcher: Callable[[str, float], Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    cleaned_query = str(query).strip()
    if not cleaned_query:
        raise ValueError("query must not be empty")
    if max_results <= 0:
        raise ValueError("max_results must be positive")

    if fetcher is None:
        def fetcher(url: str, timeout: float) -> Dict[str, Any]:
            request = Request(url, headers={"User-Agent": "tracking-agent/1.0"})
            with urlopen(request, timeout=timeout) as response:  # noqa: S310
                return json.loads(response.read().decode("utf-8"))

    payload = fetcher(
        DUCKDUCKGO_API.format(query=quote_plus(cleaned_query)),
        float(timeout_seconds),
    )
    results = _result_items(payload, max_results=max_results)
    return {
        "query": cleaned_query,
        "heading": str(payload.get("Heading", "")).strip(),
        "abstract": str(payload.get("AbstractText", "")).strip(),
        "summary": str(payload.get("AbstractText", "")).strip(),
        "summary_url": str(payload.get("AbstractURL", "")).strip(),
        "results": results,
    }


def execute_search(*, query: str, limit: int = DEFAULT_MAX_RESULTS) -> Dict[str, Any]:
    return search_web(query=query, max_results=limit)


def main() -> int:
    args = parse_args()
    if args.dry_run:
        print(
            json.dumps(
                {
                    "query": str(args.query).strip(),
                    "heading": "",
                    "abstract": "",
                    "results": [],
                },
                ensure_ascii=False,
            )
        )
        return 0

    payload = search_web(
        query=args.query,
        max_results=args.max_results,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
