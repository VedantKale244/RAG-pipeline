"""Unit tests for the Pinecone wrapper — fake clients, no network.

fetch_by_ids once assumed FetchResponse was dict-like (``res.get(...)``); on the
pinecone v7 SDK it is attribute-style only, which crashed the graph-expansion path
the first time it ever ran. The fakes here are attribute-only on purpose.
"""
from __future__ import annotations

from types import SimpleNamespace

import app.core.vectorstore as vectorstore
from app.core.vectorstore import fetch_by_ids


class FakeIndex:
    """Attribute-style FetchResponse, like the real pinecone v7 SDK — no .get()."""

    def fetch(self, ids):
        vectors = {
            cid: SimpleNamespace(metadata={"text": f"text of {cid}", "source": "doc.pdf"})
            for cid in ids
        }
        return SimpleNamespace(vectors=vectors)


class TestFetchByIds:
    def test_empty_ids_short_circuits(self):
        assert fetch_by_ids([]) == []

    def test_hydrates_attribute_style_response(self, monkeypatch):
        monkeypatch.setattr(vectorstore, "pinecone_index", lambda: FakeIndex())
        out = fetch_by_ids(["abc-123", "abc-456"])
        assert {c["chunk_id"] for c in out} == {"abc-123", "abc-456"}
        assert all(c["via_graph"] for c in out)
        assert out[0]["text"].startswith("text of ")

    def test_missing_metadata_defaults(self, monkeypatch):
        class NoMeta(FakeIndex):
            def fetch(self, ids):
                return SimpleNamespace(vectors={ids[0]: SimpleNamespace(metadata=None)})

        monkeypatch.setattr(vectorstore, "pinecone_index", lambda: NoMeta())
        out = fetch_by_ids(["x-1"])
        assert out[0]["text"] == ""
        assert out[0]["source"] == "unknown"
