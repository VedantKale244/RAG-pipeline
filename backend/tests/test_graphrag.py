"""Unit tests for the GraphRAG extraction layer — no network calls.

The prompt-format test exists because unescaped ``{...}`` in the system prompt once
became ChatPromptTemplate variables: every extraction raised KeyError, the except
clause swallowed it, and the knowledge graph stayed silently empty for every upload.
"""
from __future__ import annotations

from langchain_core.language_models.fake_chat_models import FakeListChatModel

import app.core.graphrag as graphrag
from app.core.graphrag import _EXTRACT_PROMPT, _canonicalize, _extract


class TestExtractPrompt:
    def test_formats_with_only_text_variable(self):
        # With unescaped braces this raises KeyError — the bug that emptied the graph.
        messages = _EXTRACT_PROMPT.format_messages(text="hello world")
        assert any("hello world" in m.content for m in messages)

    def test_literal_braces_survive_formatting(self):
        rendered = " ".join(m.content for m in _EXTRACT_PROMPT.format_messages(text="x"))
        assert '"entities":' in rendered
        assert '"relationships":' in rendered


class TestExtract:
    def _fake_llm(self, monkeypatch, response: str):
        monkeypatch.setattr(graphrag, "chat_llm", lambda: FakeListChatModel(responses=[response]))

    def test_returns_entities_and_relationships(self, monkeypatch):
        self._fake_llm(
            monkeypatch,
            '{"entities": [{"name": "Qodo", "type": "ORG"}],'
            ' "relationships": [{"source": "Qodo", "target": "Copilot", "rel_type": "COMPETES_WITH"}]}',
        )
        result = _extract("Qodo competes with Copilot.")
        assert result["entities"] == [{"name": "Qodo", "type": "ORG"}]
        assert result["relationships"][0]["rel_type"] == "COMPETES_WITH"

    def test_bad_json_yields_empty_not_crash(self, monkeypatch):
        self._fake_llm(monkeypatch, "not json at all")
        result = _extract("whatever")
        assert result == {"entities": [], "relationships": []}

    def test_retries_on_rate_limit(self, monkeypatch):
        from cohere.errors import TooManyRequestsError
        from langchain_core.runnables import RunnableLambda

        calls = {"n": 0}

        def flaky(_input):
            calls["n"] += 1
            if calls["n"] == 1:
                raise TooManyRequestsError(body=None)
            return '{"entities": [{"name": "X", "type": "ORG"}], "relationships": []}'

        monkeypatch.setattr(graphrag, "chat_llm", lambda: RunnableLambda(flaky))
        monkeypatch.setattr(graphrag.time, "sleep", lambda s: None)
        result = _extract("text")
        assert calls["n"] == 2
        assert result["entities"] == [{"name": "X", "type": "ORG"}]


class TestCanonicalize:
    def test_case_and_whitespace_fold(self):
        assert _canonicalize("  Apple  Inc ") == "apple inc"

    def test_alias_fold(self):
        assert _canonicalize("USA") == "united states"
