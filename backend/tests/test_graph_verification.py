"""Verification tests for Knowledge Graph operations, canonicalization, and adaptive edge weighting."""
import pytest
import numpy as np
from unittest.mock import patch, MagicMock

from app.core import graphrag
from app.core.adaptive import _decay_toward_neutral, _cosine, reweight_from_feedback


class TestKnowledgeGraphCanonicalization:
    @pytest.mark.parametrize("raw_input,expected", [
        ("NEO4J", "neo4j"),
        ("  pineCone  ", "pinecone"),
        ("GRAPH_RAG", "graph_rag"),
        ("Cohere  Rerank", "cohere rerank"),
        ("U.S.", "united states"),
        ("USA", "united states"),
        ("us", "united states"),
        (" U.S. ", "united states"),
        ("usa ", "united states"),
        ("LANGCHAIN", "langchain"),
        ("FastAPI ", "fastapi"),
        ("Neo4j DB", "neo4j db"),
        ("Pinecone Vector", "pinecone vector"),
        ("RAGAS Eval", "ragas eval"),
        ("Python 3.12", "python 3.12"),
    ])
    def test_canonicalize_variations(self, raw_input, expected):
        assert graphrag._canonicalize(raw_input) == expected

    def test_canonicalize_entities_deduplication(self):
        raw = [
            {"name": "Pinecone", "type": "PRODUCT"},
            {"name": "pinecone ", "type": "PRODUCT"},
            {"name": "USA", "type": "PLACE"},
            {"name": "United States", "type": "PLACE"},
            {"name": "FastAPI", "type": "CONCEPT"},
            {"name": "fastapi", "type": "CONCEPT"},
        ]
        processed = graphrag._canonicalize_entities(raw)
        names = [e["name"] for e in processed]
        assert names == ["pinecone", "united states", "fastapi"]

    def test_canonicalize_rels_filters_self_loops(self):
        raw = [
            {"source": "USA", "target": "united states", "rel_type": "SAME_AS"},
            {"source": "Pinecone", "target": "Neo4j", "rel_type": "INTEGRATES"},
            {"source": "Pinecone", "target": "Pinecone", "rel_type": "SELF"},
        ]
        processed = graphrag._canonicalize_rels(raw)
        assert len(processed) == 1
        assert processed[0]["source"] == "pinecone"
        assert processed[0]["target"] == "neo4j"


class TestKnowledgeGraphEdgeAdaptiveRules:
    @pytest.mark.parametrize("initial_weight,decay,expected", [
        (2.0, 0.1, 1.9),
        (0.5, 0.1, 0.55),
        (1.0, 0.1, 1.0),
        (1.05, 0.1, 1.045),
        (0.95, 0.1, 0.955),
        (1.5, 0.2, 1.4),
        (0.8, 0.2, 0.84),
        (3.0, 0.5, 2.0),
        (0.0, 0.5, 0.5),
        (1.2, 0.0, 1.2),
    ])
    def test_edge_decay_math(self, initial_weight, decay, expected):
        res = _decay_toward_neutral(initial_weight, decay)
        assert res == pytest.approx(expected, abs=0.01)

    @pytest.mark.parametrize("vec1,vec2,expected_cos", [
        ([1.0, 0.0, 0.0], [1.0, 0.0, 0.0], 1.0),
        ([1.0, 0.0, 0.0], [-1.0, 0.0, 0.0], -1.0),
        ([1.0, 0.0, 0.0], [0.0, 1.0, 0.0], 0.0),
        ([0.5, 0.5, 0.0], [1.0, 1.0, 0.0], 1.0),
        ([1.0, 2.0, 3.0], [2.0, 4.0, 6.0], 1.0),
    ])
    def test_cosine_similarity_matrix(self, vec1, vec2, expected_cos):
        v1 = np.array(vec1)
        v2 = np.array(vec2)
        assert _cosine(v1, v2) == pytest.approx(expected_cos, abs=1e-4)

    @patch("app.core.adaptive._load_graph")
    @patch("app.core.adaptive._train_embeddings")
    @patch("app.core.adaptive.neo4j_driver")
    def test_reweight_from_feedback_runs(self, mock_driver, mock_emb, mock_load):
        import networkx as nx
        g = nx.Graph()
        g.add_edge("a", "b")
        mock_load.return_value = (g, [{"source": "a", "target": "b", "rel_type": "RELATED", "weight": 1.0}])
        mock_emb.return_value = {"a": np.array([1.0, 0.0]), "b": np.array([1.0, 0.0])}
        
        session_mock = MagicMock()
        mock_driver.return_value.session.return_value.__enter__.return_value = session_mock
        
        count = reweight_from_feedback({("a", "b"): 0.9})
        assert count == 1
        assert session_mock.run.called


class TestRateLimitHelper:
    @pytest.mark.parametrize("err_msg,expected", [
        ("429 Too Many Requests", True),
        ("Rate limit exceeded", True),
        ("too many requests", True),
        ("HTTP 429 quota exhausted", True),
        ("Connection refused", False),
        ("Syntax error in cypher", False),
        ("KeyError: 'name'", False),
    ])
    def test_rate_limit_detection(self, err_msg, expected):
        assert graphrag._is_rate_limit_err(Exception(err_msg)) == expected


class TestUserScoping:
    @patch("app.core.graphrag.neo4j_driver")
    def test_graph_snapshot_empty_when_no_user_chunks(self, mock_driver):
        session_mock = MagicMock()
        session_mock.run.return_value = []
        mock_driver.return_value.session.return_value.__enter__.return_value = session_mock

        res = graphrag.graph_snapshot(user_id="fresh_guest_session")
        assert res["nodes"] == []
        assert res["edges"] == []
        assert "currently empty" in res["explanation"]

    @patch("app.core.graphrag.neo4j_driver")
    def test_graph_connects_islands_within_same_document(self, mock_driver):
        """Entities that share a source document but have no LLM-extracted RELATED edge
        must still be rendered as ONE connected component (not separate islands)."""
        session_mock = MagicMock()

        # Simulate three run() calls: edges, all entities, doc->entity mapping.
        edge_rows = [
            {"source": "alpha", "target": "beta", "rel_type": "INTEGRATES", "weight": 1.0},
        ]
        node_rows = [
            {"name": "alpha"}, {"name": "beta"}, {"name": "gamma"}, {"name": "delta"},
        ]
        doc_rows = [
            {"doc_id": "doc_1", "name": "alpha"},
            {"doc_id": "doc_1", "name": "beta"},
            {"doc_id": "doc_1", "name": "gamma"},
            {"doc_id": "doc_2", "name": "delta"},
        ]
        side_effects = iter([edge_rows, node_rows, doc_rows])
        session_mock.run.side_effect = lambda *a, **k: next(side_effects)

        mock_driver.return_value.session.return_value.__enter__.return_value = session_mock

        res = graphrag.graph_snapshot(user_id="some_user")
        node_ids = {n["id"] for n in res["nodes"]}
        node_kinds = {n["id"]: n.get("kind") for n in res["nodes"]}

        # Each source document becomes a central hub node (the file name) with spokes.
        assert "doc_1" in node_ids
        assert node_kinds["doc_1"] == "document"
        assert "alpha" in node_ids and node_kinds["alpha"] == "entity"

        # The file-name hub must be connected directly to every entity in its document.
        hub_adj = set()
        for e in res["edges"]:
            if e["source"] == "doc_1":
                hub_adj.add(e["target"])
            if e["target"] == "doc_1":
                hub_adj.add(e["source"])
        assert {"alpha", "beta", "gamma"} <= hub_adj, "file hub must speak to every entity in its doc"

        # gamma (same doc_1 as alpha/beta but no direct edge) must not be orphaned.
        assert "gamma" in node_ids
        assert "delta" in node_ids

        # delta is a separate document (doc_2) with no edges -> it is still surfaced,
        # but must NOT be force-merged into doc_1's component by the same-doc logic.
        # Verify connectivity: every doc_1 node is reachable from every other doc_1 node.
        adjacency = {n: set() for n in node_ids}
        for e in res["edges"]:
            adjacency.setdefault(e["source"], set()).add(e["target"])
            adjacency.setdefault(e["target"], set()).add(e["source"])

        def reachable(start, target):
            seen = {start}
            stack = [start]
            while stack:
                cur = stack.pop()
                if cur == target:
                    return True
                for nb in adjacency.get(cur, ()):
                    if nb not in seen:
                        seen.add(nb)
                        stack.append(nb)
            return target in seen

        for a in ("alpha", "beta", "gamma"):
            for b in ("alpha", "beta", "gamma"):
                assert reachable(a, b), f"{a} and {b} should be connected (same doc_1)"

    def test_eval_history_scoping(self, tmp_path):
        from app.eval import history
        hist_file = str(tmp_path / "eval_history.jsonl")

        history.record_eval_run(hist_file, {"user_id": "usr_A", "evaluation_mode": "ragas", "scores": {"faithfulness": 0.9}})
        history.record_eval_run(hist_file, {"user_id": "usr_B", "evaluation_mode": "ragas", "scores": {"faithfulness": 0.7}})

        runs_a = history.read_eval_runs(hist_file, user_id="usr_A")
        assert len(runs_a) == 1
        assert runs_a[0]["user_id"] == "usr_A"

        runs_fresh = history.read_eval_runs(hist_file, user_id="guest_sess_123")
        assert len(runs_fresh) == 0
