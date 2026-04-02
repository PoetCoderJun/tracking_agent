from __future__ import annotations

import json

from skills.web_search.scripts.search_web import execute_search


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_execute_search_normalizes_duckduckgo_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        "skills.web_search.scripts.search_web.urlopen",
        lambda *_args, **_kwargs: _FakeResponse(
            {
                "Heading": "OpenAI",
                "AbstractText": "OpenAI is an AI research and deployment company.",
                "AbstractURL": "https://openai.com/",
                "RelatedTopics": [
                    {
                        "Text": "OpenAI official site",
                        "FirstURL": "https://openai.com/",
                    },
                    {
                        "Topics": [
                            {
                                "Text": "ChatGPT",
                                "FirstURL": "https://chatgpt.com/",
                            }
                        ]
                    },
                ],
            }
        ),
    )

    payload = execute_search(query="OpenAI", limit=5)

    assert payload["query"] == "OpenAI"
    assert payload["heading"] == "OpenAI"
    assert payload["summary"] == "OpenAI is an AI research and deployment company."
    assert payload["summary_url"] == "https://openai.com/"
    assert payload["results"][0]["url"] == "https://openai.com/"
    assert payload["results"][1]["text"] == "ChatGPT"
