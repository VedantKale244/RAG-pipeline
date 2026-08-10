"""Unit tests for chat_llm() automatic Groq -> Cohere fallback — no network calls."""
from __future__ import annotations

import sys
import types

from langchain_core.language_models.chat_models import BaseChatModel, ChatGeneration, ChatResult
from langchain_core.messages import AIMessage, HumanMessage

from app.core import clients


class _FailingGroq(BaseChatModel):
    def _generate(self, messages, stop=None, run_manager=None, **kw):
        raise Exception("429 Too many requests: daily token limit reached")

    @property
    def _llm_type(self) -> str:
        return "failing-groq"


class _HealthyCohere(BaseChatModel):
    def _generate(self, messages, stop=None, run_manager=None, **kw):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="cohere answer"))])

    @property
    def _llm_type(self) -> str:
        return "healthy-cohere"


class _FakeChatGroq:
    """Stands in for langchain_groq.ChatGroq so chat_llm() builds without a live key."""

    def __init__(self, *args, **kwargs):
        self.model = kwargs.get("model")
        self._wrapped = _FailingGroq()

    def with_fallbacks(self, fallbacks, **kwargs):
        self._wrapped = self._wrapped.with_fallbacks(fallbacks, **kwargs)
        return self

    def invoke(self, input, **kwargs):
        return self._wrapped.invoke(input, **kwargs)

    def stream(self, input, **kwargs):
        return self._wrapped.stream(input, **kwargs)


def _install_fake_groq(monkeypatch):
    module = types.ModuleType("langchain_groq")
    module.ChatGroq = _FakeChatGroq
    monkeypatch.setitem(sys.modules, "langchain_groq", module)
    monkeypatch.setattr(clients, "_cohere_llm", lambda: _HealthyCohere())
    monkeypatch.setattr(clients.settings, "groq_api_key", "gsk_fake_for_test")
    clients.chat_llm.cache_clear()


def test_chat_llm_falls_back_to_cohere_on_groq_429(monkeypatch):
    _install_fake_groq(monkeypatch)
    llm = clients.chat_llm()
    msg = HumanMessage(content="what is the answer?")
    assert llm.invoke([msg]).content == "cohere answer"
    assert [c.content for c in llm.stream([msg])] == ["cohere answer"]


def test_chat_llm_without_groq_key_uses_cohere_only(monkeypatch):
    monkeypatch.setattr(clients, "_cohere_llm", lambda: _HealthyCohere())
    monkeypatch.setattr(clients.settings, "groq_api_key", "")
    clients.chat_llm.cache_clear()
    llm = clients.chat_llm()
    assert llm.invoke([HumanMessage(content="hi")]).content == "cohere answer"