"""Unit tests for the optimization-pass logic: canonicalization, rerank floor,
edge decay, token sizing. Pure functions + one mocked-client path — no live services."""
from __future__ import annotations

from app.core.adaptive import _decay_toward_neutral
from app.core.graphrag import _canonicalize, _canonicalize_entities, _canonicalize_rels
from app.core.ingestion import _token_len
from app.core.retrieval import _cohere_rerank


class TestCanonicalize:
    def test_case_and_whitespace_fold(self):
        assert _canonicalize("  Apple  Inc ") == _canonicalize("apple inc")

    def test_alias_map(self):
        assert _canonicalize("USA") == "united states"
        assert _canonicalize("U.S.") == "united states"

    def test_entities_deduped_after_folding(self):
        ents = [{"name": "Apple", "type": "ORG"}, {"name": "apple ", "type": "ORG"}]
        out = _canonicalize_entities(ents)
        assert len(out) == 1
        assert out[0]["name"] == "apple"

    def test_rels_drop_self_loops_created_by_folding(self):
        rels = [{"source": "Apple", "target": "APPLE", "rel_type": "IS"}]
        assert _canonicalize_rels(rels) == []

    def test_rels_drop_empty_endpoints(self):
        rels = [{"source": "", "target": "b", "rel_type": "IS"}]
        assert _canonicalize_rels(rels) == []


class TestEdgeDecay:
    def test_decays_high_weight_toward_one(self):
        assert 1.0 < _decay_toward_neutral(2.0, 0.05) < 2.0

    def test_decays_low_weight_toward_one(self):
        assert 0.05 < _decay_toward_neutral(0.05, 0.05) < 1.0

    def test_neutral_is_fixpoint(self):
        assert _decay_toward_neutral(1.0, 0.05) == 1.0

    def test_full_decay_snaps_to_neutral(self):
        assert _decay_toward_neutral(1.7, 1.0) == 1.0

    def test_zero_decay_is_identity(self):
        assert _decay_toward_neutral(1.7, 0.0) == 1.7


class TestTokenLen:
    def test_positive_for_text(self):
        assert _token_len("hello world, this is a chunk of text") > 0

    def test_scales_with_length(self):
        assert _token_len("word " * 400) > _token_len("word " * 10)


class TestRerankFloor:
    """Passages below settings.rerank_min_score must be dropped."""

    def _mock(self, monkeypatch, scores):
        class R:
            def __init__(self, i, s):
                self.index, self.relevance_score = i, s

        class Resp:
            def __init__(self):
                self.results = [R(i, s) for i, s in enumerate(scores)]

        class Client:
            def rerank(self, **kw):
                return Resp()

        import app.core.retrieval as mod

        monkeypatch.setattr(mod, "cohere_client", lambda: Client())

    def _c(self, cid):
        return {"chunk_id": cid, "text": f"t{cid}", "source": "s", "score": 0.0,
                "via_graph": False}

    def test_weak_passages_dropped(self, monkeypatch):
        self._mock(monkeypatch, [0.9, 0.05, 0.5, 0.01])
        out = _cohere_rerank("q", [self._c(str(i)) for i in range(4)], top_n=4)
        assert [c["chunk_id"] for c in out] == ["0", "2"]

    def test_all_weak_soft_abstains_with_top3(self, monkeypatch):
        # The floor must not hard-empty the context — meta-questions ("what is this
        # doc about?") score ~0.01 against every chunk. Top-ranked passages pass
        # through and the generation prompt decides sufficiency.
        self._mock(monkeypatch, [0.02, 0.01])
        out = _cohere_rerank("q", [self._c("a"), self._c("b")], top_n=2)
        assert [c["chunk_id"] for c in out] == ["a", "b"]
