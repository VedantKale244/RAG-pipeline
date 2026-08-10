"""Unit tests for the retrieval core — no external API calls."""
from __future__ import annotations

from app.core.retrieval import _cohere_rerank, _dedupe


def _c(chunk_id: str, text: str = "x", score: float = 0.5, via_graph: bool = False):
    return {"chunk_id": chunk_id, "text": text, "source": "test.txt",
            "score": score, "via_graph": via_graph}


class TestDedupe:
    def test_removes_exact_duplicates(self):
        candidates = [_c("a"), _c("a"), _c("b")]
        result = _dedupe(candidates)
        ids = [r["chunk_id"] for r in result]
        assert ids.count("a") == 1
        assert "b" in ids

    def test_prefers_record_with_text(self):
        empty = {"chunk_id": "a", "text": "", "source": "s", "score": 0.9, "via_graph": False}
        rich  = {"chunk_id": "a", "text": "hello", "source": "s", "score": 0.0, "via_graph": True}
        result = _dedupe([empty, rich])
        assert len(result) == 1
        assert result[0]["text"] == "hello"

    def test_preserves_order_of_first_seen(self):
        candidates = [_c("b"), _c("a"), _c("c")]
        result = _dedupe(candidates)
        assert [r["chunk_id"] for r in result] == ["b", "a", "c"]

    def test_empty_input(self):
        assert _dedupe([]) == []


class TestCohereRerank:
    """Patch the Cohere client so no network call is made."""

    def _mock_rerank(self, monkeypatch, scores: list[float]):
        class FakeResult:
            def __init__(self, index, relevance_score):
                self.index = index
                self.relevance_score = relevance_score

        class FakeResp:
            def __init__(self, scores):
                self.results = [FakeResult(i, s) for i, s in enumerate(scores)]

        class FakeClient:
            def rerank(self, **kwargs):
                docs = kwargs["documents"]
                top_n = kwargs.get("top_n", len(docs))
                # The real Cohere API returns at most top_n results.
                return FakeResp(scores[: min(top_n, len(docs))])

        import app.core.retrieval as mod
        monkeypatch.setattr(mod, "cohere_client", lambda: FakeClient())

    def test_returns_top_n(self, monkeypatch):
        self._mock_rerank(monkeypatch, [0.9, 0.8, 0.7, 0.6])
        candidates = [_c(str(i), text=f"text {i}") for i in range(4)]
        result = _cohere_rerank("q", candidates, top_n=2)
        assert len(result) == 2

    def test_scores_are_applied(self, monkeypatch):
        self._mock_rerank(monkeypatch, [0.42])
        candidates = [_c("a", text="hello")]
        result = _cohere_rerank("q", candidates, top_n=1)
        assert abs(result[0]["score"] - 0.42) < 1e-6

    def test_empty_candidates(self, monkeypatch):
        self._mock_rerank(monkeypatch, [])
        assert _cohere_rerank("q", [], top_n=5) == []

    def test_floor_filters_low_scores(self, monkeypatch):
        self._mock_rerank(monkeypatch, [0.9, 0.01])
        candidates = [_c("a"), _c("b")]
        result = _cohere_rerank("q", candidates, top_n=2)
        assert [r["chunk_id"] for r in result] == ["a"]

    def test_floor_fallback_when_all_below(self, monkeypatch):
        # Meta-questions rerank near zero against every chunk — the floor must
        # soft-abstain (top 3 through) rather than return nothing.
        self._mock_rerank(monkeypatch, [0.02, 0.01, 0.005, 0.001])
        candidates = [_c(str(i), text=f"text {i}") for i in range(4)]
        result = _cohere_rerank("q", candidates, top_n=4)
        assert [r["chunk_id"] for r in result] == ["0", "1", "2"]


class TestGraphEntitySummaries:
    def test_fetch_graph_entity_summaries_mock(self, monkeypatch):
        class FakeRecord(dict):
            pass

        class FakeSession:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def run(self, query, **kwargs):
                return [
                    FakeRecord({
                        "name": "Prometheus",
                        "type": "TECHNOLOGY",
                        "rationale": "Monitoring system.",
                        "rels": [{"neighbor": "Elastic", "rel_type": "CO_OCCURS"}],
                    })
                ]

        class FakeDriver:
            def session(self):
                return FakeSession()

        import app.core.graphrag as graphrag
        monkeypatch.setattr(graphrag, "neo4j_driver", lambda: FakeDriver())

        from app.core.retrieval import fetch_graph_entity_summaries
        res = fetch_graph_entity_summaries("What is Prometheus?", "user1")
        assert len(res) == 1
        assert res[0]["chunk_id"] == "kg_entity_Prometheus"
        assert "Prometheus" in res[0]["text"]
        assert "Elastic" in res[0]["text"]
        assert res[0]["via_graph"] is True

