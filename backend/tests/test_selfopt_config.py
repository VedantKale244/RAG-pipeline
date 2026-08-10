"""Tests for the selfopt settings fields.

Two of these fields were module-level constants in `adaptive.py` before the
optimizer needed to tune them. Promoting a constant to a setting is exactly the
kind of change that silently alters behavior, so the defaults are pinned here.
"""
from __future__ import annotations

import networkx as nx
import numpy as np
import torch

from app.config import settings
from app.core import adaptive


def test_graphsage_defaults_match_former_constants():
    # These were `_ALPHA` and `_EPOCHS` in adaptive.py. If either default drifts,
    # every graph the system has already trained was built under other numbers.
    assert settings.graphsage_alpha == 0.6
    assert settings.graphsage_epochs == 15


def test_selfopt_control_defaults():
    assert settings.selfopt_enabled is True
    assert settings.selfopt_tick_seconds == 300
    assert settings.selfopt_canary_percent == 15
    assert settings.selfopt_min_canary_queries == 40


def test_adaptive_reads_epochs_from_settings_at_call_time(monkeypatch):
    # A module-scope read would capture the value at import and the override
    # layer would never be seen. Patching after import must still take effect.
    monkeypatch.setattr(settings, "graphsage_epochs", 2, raising=False)

    g = nx.Graph()
    g.add_edges_from([("a", "b"), ("b", "c"), ("c", "a")])

    # _train_embeddings runs settings.graphsage_epochs iterations. Count backward
    # calls to measure it indirectly.
    steps = []
    real_backward = torch.Tensor.backward

    def counting_backward(self, *args, **kwargs):
        steps.append(1)
        return real_backward(self, *args, **kwargs)

    monkeypatch.setattr(torch.Tensor, "backward", counting_backward)
    adaptive._train_embeddings(g)

    # One backward call per epoch.
    assert len(steps) == 2


def test_adaptive_reads_alpha_from_settings_at_call_time(monkeypatch):
    # Drives the real call site in reweight_from_feedback, stubbing only its
    # graph/Neo4j edges. alpha=1.0 makes the blend pure-structural (reward drops
    # out); alpha=0.0 makes it pure-reward. A module-scope _ALPHA read would
    # ignore both and return the same weight twice.
    g = nx.Graph()
    g.add_edges_from([("a", "b")])
    edges = [{"source": "a", "target": "b", "rel_type": "RELATED", "weight": 1.0}]

    # Orthogonal embeddings → cosine 0 → structural = 0.5 exactly.
    embeddings = {
        "a": np.array([1.0, 0.0], dtype=np.float32),
        "b": np.array([0.0, 1.0], dtype=np.float32),
    }
    monkeypatch.setattr(adaptive, "_load_graph", lambda: (g, edges))
    monkeypatch.setattr(adaptive, "_train_embeddings", lambda _g: embeddings)

    captured = []

    class _Session:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def run(self, _query, updates):
            captured.extend(updates)

    monkeypatch.setattr(adaptive, "neo4j_driver", lambda: type("D", (), {"session": lambda _s: _Session()})())

    # structural = 0.5, reward = 1.0. Stored weight is clamped round(w * 2, 4).
    monkeypatch.setattr(settings, "graphsage_alpha", 1.0, raising=False)
    adaptive.reweight_from_feedback({("a", "b"): 1.0})
    assert captured[-1]["w"] == 1.0  # 1.0*0.5 + 0.0*1.0 = 0.5 → *2

    monkeypatch.setattr(settings, "graphsage_alpha", 0.0, raising=False)
    adaptive.reweight_from_feedback({("a", "b"): 1.0})
    assert captured[-1]["w"] == 2.0  # 0.0*0.5 + 1.0*1.0 = 1.0 → *2
