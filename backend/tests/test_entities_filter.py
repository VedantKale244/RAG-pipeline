"""Regression tests: ordinary English words must never become Knowledge Graph entities.

The Knowledge Graph must contain only what the extractor is designed for (real
domain entities). Filler/function words reported in production — "let", "thus",
"may", "also", "now", etc. — are deterministically rejected by ``_is_valid_entity``
both here and at the write gate, so they can never be written again.
"""
from __future__ import annotations

import pytest

from app.core.graphrag import _ENGLISH_NON_ENTITIES, _is_valid_entity, purge_invalid_entities_from_db


# Words/forms the user reported polluting the graph, plus classic fillers.
JUNK = [
    "let", "lets", "let's", "let us", "thus", "then", "hence", "may", "maybe",
    "might", "can", "could", "would", "will", "shall", "should", "must", "and",
    "or", "but", "so", "because", "although", "though", "however", "whereas",
    "therefore", "meanwhile", "furthermore", "moreover", "this", "these", "those",
    "that", "its", "it", "they", "their", "there", "here", "now", "also", "even",
    "just", "again", "once", "many", "some", "such", "more", "most", "each",
    "every", "overall", "typically", "probably", "perhaps", "certainly",
    "mean", "says", "said", "telling", "trying", "imagine", "suppose",
    # Multi-word all-filler phrases
    "let us try", "we should", "and then", "in this case", "may be used",
    "then use", "there are many",
    # Contracted fillers (apostrophes stripped)
    "can't", "don't", "won't", "it's", "that's", "they're",
]

# Genuine domain entities that must never be rejected.
REAL = [
    "OpenAPI",
    "Pinecone Serverless",
    "Cohere Embed",
    "Neo4j Graph",
    "Python",
    "RAG Pipeline",
    "retrieval augmented generation",
    "vector database",
    "transformer architecture",
    "GraphRAG",
    "BERT score",
    "GraphSAGE",
    "metadata index",
    "semantic caching",
    "query expansion",
    "hybrid search",
    # Real compound terms whose components are otherwise junk alone
    "Merge Sort",
    "Quick Sort",
    "Binary Search",
    "Binary Tree Representation",
    "Dynamic Programming",
    "Priority Queue",
    "Circular Queue",
    "Linked Representation",
    "Division Method",
    "Mid Square",
    "Autonomous Institution",
    "Project Atlas",
    "Redis Cluster",
]

# Corpus-observed generic words that must never survive as standalone entities.
JUNK_MORE = [
    "Approved", "Accredited", "Affiliated", "Recognized", "Govt", "Gov",
    "Best", "Worst", "Complete", "Empty", "Invalid", "Initially", "Secondly",
    "Consider", "Divide", "End", "Home", "Enter", "Height", "Insert",
    "Insertion", "Deletion", "Deletions", "Proof", "Theorem", "Note",
    "Operations", "Nodes", "Searching", "Popping", "Underflow", "Max",
    "Prime", "Bucket", "Algorithm", "Since", "Linear List Representation The",
    "Queue Sucesfully", "Steps",
]


@pytest.mark.parametrize("name", JUNK, ids=lambda n: f"junk:{n}")
def test_junk_words_are_never_valid_entities(name):
    assert _is_valid_entity(name) is False


@pytest.mark.parametrize("name", JUNK_MORE, ids=lambda n: f"corpus_junk:{n}")
def test_corpus_noise_never_valid_entities(name):
    assert _is_valid_entity(name) is False


@pytest.mark.parametrize("name", REAL, ids=lambda n: f"real:{n}")
def test_real_domain_entities_stay_valid(name):
    assert _is_valid_entity(name) is True


def test_empty_and_trivial_names_are_rejected():
    assert _is_valid_entity("") is False
    assert _is_valid_entity("   ") is False
    assert _is_valid_entity("a") is False
    assert _is_valid_entity("123") is False
    assert _is_valid_entity("!!!") is False


def test_blocklist_contains_reported_offenders():
    for w in ("let", "thus", "may", "also", "now", "maybe", "then", "however"):
        assert w in _ENGLISH_NON_ENTITIES


def test_purge_invalid_entities_passes_only_junk_to_delete(monkeypatch):
    """The DB purge must target exactly the names that fail the gate."""
    captured = {}

    class _Count:
        def single(self):
            class _C:
                def __getitem__(self, k):
                    return 1
            return _C()

    class _Rows:
        def __init__(self, rows):
            self._rows = rows

        def __iter__(self):
            return iter(self._rows)

    class _Session:
        def run(self, query, **params):
            if "RETURN e.name AS name" in query:
                return _Rows([{"name": "Let"}, {"name": "Pinecone"}])
            captured["invalid_names"] = params.get("invalid_names", [])
            return _Count()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _Driver:
        def session(self):
            return _Session()

    monkeypatch.setattr("app.core.graphrag.neo4j_driver", lambda: _Driver())
    purge_invalid_entities_from_db()
    assert "let" in captured["invalid_names"]
    assert "pinecone" not in captured["invalid_names"]