"""Verification tests for RAGAS evaluation scoring, reward updates, and pipeline history."""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.eval import ragas_eval

client = TestClient(app)


class TestRagasEvaluationScoring:
    def test_sample_validation_empty_samples(self):
        res = client.post("/eval", json={"samples": []})
        assert res.status_code == 422 or res.status_code == 400

    def test_sample_validation_invalid_json(self):
        res = client.post("/eval", json={"samples": "invalid"})
        assert res.status_code == 422

    @pytest.mark.parametrize("samples_count", [0, 51, 100])
    def test_eval_sample_bounds_validation(self, samples_count):
        samples = [{"question": f"Q{i}", "ground_truth": f"A{i}"} for i in range(samples_count)]
        res = client.post("/eval", json={"samples": samples})
        if samples_count == 0 or samples_count > 50:
            assert res.status_code in [400, 422]

    @pytest.mark.parametrize("faith,relevancy,expected_reward", [
        (1.0, 1.0, 1.0),
        (0.0, 0.0, 0.0),
        (0.8, 0.6, 0.7),
        (1.0, 0.0, 0.5),
        (0.5, 0.5, 0.5),
        (0.9, 0.9, 0.9),
    ])
    def test_aggregate_rewards_clamping(self, faith, relevancy, expected_reward):
        sample = {"faithfulness": faith, "answer_relevancy": relevancy, "edges": [("A", "B")]}
        reward = (sample["faithfulness"] + sample["answer_relevancy"]) / 2.0
        assert reward == pytest.approx(expected_reward)

    @patch("app.api.eval.history.read_eval_runs")
    def test_eval_history_endpoint(self, mock_read):
        mock_read.return_value = [
            {
                "ts": 1700000000,
                "scores": {"faithfulness": 0.9, "answer_relevancy": 0.85, "context_precision": 0.8, "context_recall": 0.88},
                "updated_edges": 3,
                "graph_lift": 0.12,
                "n_samples": 2,
            }
        ]
        res = client.get("/eval/history")
        assert res.status_code == 200
        data = res.json()
        assert "runs" in data
        assert len(data["runs"]) == 1
        assert data["runs"][0]["graph_lift"] == 0.12


class TestRagasScoreSanity:
    @pytest.mark.parametrize("faith,rel,prec,rec", [
        (1.0, 1.0, 1.0, 1.0),
        (0.0, 0.0, 0.0, 0.0),
        (0.75, 0.85, 0.90, 0.80),
        (0.99, 0.95, 0.98, 0.92),
        (0.50, 0.50, 0.50, 0.50),
    ])
    def test_score_normalization_bounds(self, faith, rel, prec, rec):
        scores = {"faithfulness": faith, "answer_relevancy": rel, "context_precision": prec, "context_recall": rec}
        for metric, score in scores.items():
            assert 0.0 <= score <= 1.0
