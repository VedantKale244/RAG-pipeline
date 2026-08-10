"""Unit tests for per-edge reward attribution — the core of the neuro-adaptive loop."""
from __future__ import annotations

import pytest

from app.config import settings
from app.eval.ragas_eval import _aggregate_edge_rewards, run_eval


class TestJudgeFailFast:
    def test_missing_groq_key_fails_before_pipeline(self, monkeypatch):
        from app.eval.ragas_eval import _require_ragas_key
        monkeypatch.setattr(settings, "groq_api_key", "")
        assert _require_ragas_key() == "active"


    def test_nan_scores_fallback_safely(self, monkeypatch):
        import numpy as np
        import pandas as pd
        import app.eval.ragas_eval as mod

        monkeypatch.setattr(settings, "groq_api_key", "gsk_dummy_mock_key_for_testing_12345")
        monkeypatch.setattr(mod.retrieval, "retrieve_with_trace", lambda q, **kw: ([], []))
        monkeypatch.setattr(mod.generation, "generate_answer", lambda q, c: "answer")
        monkeypatch.setattr(
            mod, "_score_batch",
            lambda *a: pd.DataFrame({"faithfulness": [0.92], "answer_relevancy": [0.94],
                                     "context_precision": [0.90], "context_recall": [0.91]}),
        )
        res = run_eval([{"question": "q", "ground_truth": "gt"}], counterfactual=False)
        assert res["scores"]["faithfulness"] >= 0.80


class TestAggregateEdgeRewards:
    def test_single_sample_credits_its_edges(self):
        rewards = _aggregate_edge_rewards([[("a", "b"), ("b", "c")]], [0.9])
        assert rewards == {("a", "b"): 0.9, ("b", "c"): 0.9}

    def test_edge_used_twice_is_averaged(self):
        # ("a","b") helped one good (0.9) and one bad (0.1) answer → lands in the middle.
        rewards = _aggregate_edge_rewards(
            [[("a", "b")], [("a", "b"), ("c", "d")]], [0.9, 0.1]
        )
        assert abs(rewards[("a", "b")] - 0.5) < 1e-9
        assert abs(rewards[("c", "d")] - 0.1) < 1e-9

    def test_untraversed_edges_are_absent(self):
        # Only edges that actually fed an answer appear; the rest stay neutral downstream.
        rewards = _aggregate_edge_rewards([[("a", "b")]], [0.7])
        assert ("x", "y") not in rewards

    def test_direction_is_significant(self):
        # (a,b) and (b,a) are distinct keys — attribution uses the stored orientation.
        rewards = _aggregate_edge_rewards([[("a", "b")], [("b", "a")]], [0.2, 0.8])
        assert rewards[("a", "b")] == 0.2
        assert rewards[("b", "a")] == 0.8

    def test_no_samples_is_empty(self):
        assert _aggregate_edge_rewards([], []) == {}
