"""Regressions for three bugs that failed silently in production.

Each of these was invisible at runtime: the code logged a warning (or nothing) and
returned an empty/plausible result, so the pipeline looked healthy while being broken.
"""
from __future__ import annotations

import pytest

import app.core.clients as clients
from app.core.clients import EmbeddingUnavailable, safe_embed_documents, safe_embed_query
from app.core.graphrag import _EXPAND_CYPHER_TMPL, _WRITE_CYPHER


class TestExpandCypherTemplate:
    """expand() used str.format() on Cypher containing a literal map `{name: ...}`.

    format() read that as a replacement field and raised KeyError('name') on every
    call. retrieve_with_trace caught it as "Graph expansion failed safely", so graph
    expansion returned zero results for the entire life of the project.
    """

    def test_format_would_raise_keyerror(self):
        # Now that expand() carries version-isolating {seed_vc}/{c_vc} placeholders,
        # format() trips on the first missing key before the literal {name: ...} map.
        with pytest.raises(KeyError, match="(seed_vc|name)"):
            _EXPAND_CYPHER_TMPL.format(hops=2)

    def test_replace_substitutes_hops_and_keeps_map_literal(self):
        q = _EXPAND_CYPHER_TMPL.replace("{hops}", "2")
        assert "{hops}" not in q
        assert "RELATED*1..2" in q
        assert "{name: n.name, embedding: n.embedding}" in q


class TestWriteCypherParameters:
    """The Neo4j ParameterMissing error: _WRITE_CYPHER declares $text, but the caller
    did not pass it, so every ingest aborted with ParameterMissing.
    """

    def test_declared_params_are_all_supplied_by_caller(self):
        import re

        declared = set(re.findall(r"\$(\w+)", _WRITE_CYPHER))
        supplied = {"chunk_id", "source", "document_id", "user_id", "text",
                    "entities", "relationships"}
        assert declared <= supplied, f"Cypher needs unsupplied params: {declared - supplied}"

    def test_text_is_declared(self):
        assert "$text" in _WRITE_CYPHER


class TestNoFabricatedEmbeddings:
    """Embedding failures fell back to a sha256-derived vector. Those are
    indistinguishable from real embeddings once in Pinecone, so a dead API key
    silently and permanently corrupted the index instead of failing.
    """

    def _boom(self, msg):
        class Dead:
            def embed_query(self, *a, **k):
                raise RuntimeError(msg)

            def embed_documents(self, *a, **k):
                raise RuntimeError(msg)

        return lambda: Dead()

    def test_quota_error_raises_not_fabricates(self, monkeypatch):
        from app.core import clients
        def _boom_provider():
            class BoomProvider:
                def embed_documents(self, texts):
                    raise EmbeddingUnavailable("quota: limited to 1000 API calls / month")
                def embed_query(self, text):
                    raise EmbeddingUnavailable("quota: limited to 1000 API calls / month")
                def validate_dimension(self):
                    pass
            return BoomProvider()

        monkeypatch.setattr(clients, "get_embedding_provider", _boom_provider)
        with pytest.raises(EmbeddingUnavailable, match="quota"):
            safe_embed_query("hello")
        with pytest.raises(EmbeddingUnavailable):
            safe_embed_documents(["a", "b"])


    def test_no_deterministic_vector_helper_remains(self):
        assert not hasattr(clients, "_deterministic_vector"), (
            "hash-based fake embeddings must stay deleted - they corrupt the index"
        )

    def test_documents_stay_aligned_with_input(self, monkeypatch):
        """upsert_chunks zips this against the batch; a length mismatch misassigns
        every vector to the wrong chunk."""
        class Ok:
            def embed_documents(self, docs):
                return [[0.1] * 4 for _ in docs]

        monkeypatch.setattr(clients, "embeddings", lambda: Ok())
        assert len(safe_embed_documents(["a", "", "c"])) == 3

    def test_empty_query_rejected(self):
        with pytest.raises(EmbeddingUnavailable):
            safe_embed_query("   ")
