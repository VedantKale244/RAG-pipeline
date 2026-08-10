"""Unit tests for ingestion helpers — pure functions, no I/O."""
from __future__ import annotations

from app.core.ingestion import _chunk_id, _document_id


class TestChunkId:
    def test_is_deterministic(self):
        assert _chunk_id("doc1", "some text", 0) == _chunk_id("doc1", "some text", 0)

    def test_starts_with_document_id(self):
        assert _chunk_id("doc42", "text", 3).startswith("doc42-")

    def test_differs_by_index(self):
        assert _chunk_id("doc1", "text", 0) != _chunk_id("doc1", "text", 1)

    def test_differs_by_document(self):
        assert _chunk_id("docA", "text", 0) != _chunk_id("docB", "text", 0)

    def test_differs_by_text(self):
        assert _chunk_id("doc1", "alpha", 0) != _chunk_id("doc1", "beta", 0)


class TestDocumentId:
    def test_same_filename_is_stable(self):
        # the whole point: re-uploading the same name reuses the id → dedup fires
        assert _document_id("report.pdf") == _document_id("report.pdf")

    def test_differs_by_filename(self):
        assert _document_id("a.pdf") != _document_id("b.pdf")

    def test_prefixes_its_chunk_ids(self):
        did = _document_id("report.pdf")
        assert _chunk_id(did, "text", 0).startswith(f"{did}-")
