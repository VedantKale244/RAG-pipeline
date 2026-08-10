"""Neuro-adaptive graph embeddings.

The knowledge graph's ``RELATED`` edges start with a flat weight of 1.0. This module
learns node embeddings over that graph with a GraphSAGE encoder and then *adapts* the
edge weights using two signals:

1. **Structural signal** — cosine similarity between the learned embeddings of the two
   endpoint entities (edges between structurally-similar nodes are strengthened).
2. **Feedback signal** — a per-edge reward derived from RAGAS scores of the answers whose
   retrieval traversed that edge. Edges that contributed to faithful, relevant answers
   get boosted; edges on paths that produced hallucinated or off-topic answers decay.

The updated weights feed straight back into ``graphrag.expand``'s weighted traversal, so
retrieval quality compounds over time. This is the concrete implementation behind the
"neuro-adaptive graph embedding" concept: embeddings + eval feedback jointly reshape the
graph the retriever walks.
"""
from __future__ import annotations

from pathlib import Path

import networkx as nx
import numpy as np
import torch
import torch.nn.functional as F
from torch_geometric.nn import SAGEConv
from torch_geometric.utils import from_networkx

from ..config import settings
from .clients import neo4j_driver

_EMB_DIM = 64
_LR = 0.01
# _EPOCHS and _ALPHA moved to Settings (graphsage_epochs, graphsage_alpha) so the
# optimizer can tune them. _EMB_DIM and _LR stay constant: changing _EMB_DIM
# invalidates every cached embedding.


def _feature_matrix(g: nx.Graph, nodes: list[str]) -> torch.Tensor:
    """Deterministic node features: [log-degree, clustering].

    Replaces the old ``torch.randn`` init. Random features made every run's embeddings
    incomparable, so the structural signal was noise. These are cheap, deterministic,
    structure-derived features — projected up by the first SAGEConv — so warm-starting
    across runs actually accumulates rather than relearning from scratch.
    """
    clustering = nx.clustering(g)
    feats = []
    for n in nodes:
        deg = g.degree(n)
        feats.append([np.log1p(deg), clustering.get(n, 0.0)])
    return torch.tensor(feats, dtype=torch.float32)


def _cache_path() -> Path:
    return Path(settings.embedding_cache_path)


def _load_cached_state() -> dict | None:
    p = _cache_path()
    if not p.exists():
        return None
    try:
        # weights_only=True: the cache is only a state_dict of tensors, so refuse to
        # unpickle arbitrary objects (avoids code-exec on a tampered cache file).
        return torch.load(p, map_location="cpu", weights_only=True)
    except Exception:  # ponytail: corrupt/old cache → cold start, not a crash
        return None


def _save_state(model: torch.nn.Module) -> None:
    p = _cache_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        torch.save(model.state_dict(), p)
    except Exception:
        pass  # persistence is best-effort; a failed save just means a cold next run


class _GraphSAGE(torch.nn.Module):
    """Two-layer GraphSAGE encoder producing node embeddings."""

    def __init__(self, in_dim: int, hidden: int, out_dim: int):
        super().__init__()
        self.conv1 = SAGEConv(in_dim, hidden)
        self.conv2 = SAGEConv(hidden, out_dim)

    def forward(self, x, edge_index):
        h = F.relu(self.conv1(x, edge_index))
        return self.conv2(h, edge_index)


def _load_graph() -> tuple[nx.Graph, list[dict]]:
    """Pull the entity graph out of Neo4j (or the SQLite fallback) into a NetworkX graph."""
    g = nx.Graph()
    edges: list[dict] = []
    try:
        with neo4j_driver().session() as session:
            rows = session.run(
                "MATCH (a:Entity)-[r:RELATED]->(b:Entity) "
                "RETURN a.name AS s, b.name AS t, r.rel_type AS rt, r.weight AS w"
            )
            for row in rows:
                g.add_node(row["s"])
                g.add_node(row["t"])
                g.add_edge(row["s"], row["t"])
                edges.append(
                    {"source": row["s"], "target": row["t"], "rel_type": row["rt"],
                     "weight": float(row["w"] or 1.0)}
                )
    except Exception as exc:
        if _neo4j_down(exc):
            from .fallback_graph import load_graph_edges
            return load_graph_edges()
        raise
    return g, edges


def _neo4j_down(exc: Exception) -> bool:
    """Best-effort detection of an unreachable graph store (mirrors graphrag)."""
    from .graphrag import _is_neo4j_unavailable
    return _is_neo4j_unavailable(exc)


def _train_embeddings(g: nx.Graph) -> dict[str, np.ndarray]:
    """Self-supervised GraphSAGE (link-prediction) with warm-start + real features.

    Two changes from the naive version that made the structural signal trustworthy:
      * node features are deterministic structural stats (see _feature_matrix), not
        random noise — so embeddings mean the same thing across runs;
      * model weights warm-start from the last run's cached state_dict when the input
        dimension matches, so the loop *accumulates* structure instead of relearning it.
    """
    if g.number_of_nodes() < 3 or g.number_of_edges() < 2:
        return {}

    nodes = list(g.nodes())
    idx = {n: i for i, n in enumerate(nodes)}
    data = from_networkx(g)
    in_dim = 2  # _feature_matrix width; kept explicit so the cache dim-check is obvious
    data.x = _feature_matrix(g, nodes)

    model = _GraphSAGE(in_dim, 128, _EMB_DIM)
    cached = _load_cached_state()
    if cached is not None:
        try:
            model.load_state_dict(cached)  # warm-start
        except Exception:
            pass  # architecture changed → cold start
    opt = torch.optim.Adam(model.parameters(), lr=_LR)
    edge_index = data.edge_index
    existing = {(int(s), int(d)) for s, d in edge_index.t().tolist()}

    model.train()
    # Read inside the function, not at module scope: a module-level read captures
    # the value at import and the selfopt override layer would never be seen.
    for _ in range(settings.graphsage_epochs):
        opt.zero_grad()
        z = model(data.x, edge_index)
        src, dst = edge_index
        pos = (z[src] * z[dst]).sum(dim=1)
        # negatives = random pairs, resampled if they collide with a real edge
        neg_dst = torch.randint(0, len(nodes), (dst.size(0),))
        for i in range(neg_dst.size(0)):
            tries = 0
            while (int(src[i]), int(neg_dst[i])) in existing and tries < 5:
                neg_dst[i] = torch.randint(0, len(nodes), (1,)).item()
                tries += 1
        neg = (z[src] * z[neg_dst]).sum(dim=1)
        loss = -F.logsigmoid(pos).mean() - F.logsigmoid(-neg).mean()
        loss.backward()
        opt.step()

    _save_state(model)
    model.eval()
    with torch.no_grad():
        z = model(data.x, edge_index).cpu().numpy()
    return {n: z[idx[n]] for n in nodes}


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) + 1e-9
    return float(np.dot(a, b) / denom)


def _decay_toward_neutral(weight: float, decay: float, neutral: float = 1.0) -> float:
    """Pull an untouched edge's weight a fraction ``decay`` toward neutral.

    Edges no eval ever traverses would otherwise stay frozen at whatever value the first
    few runs happened to assign — the graph ossifies. Decaying them back toward 1.0 keeps
    it plastic ("the graph forgets connections nobody uses"). Idempotent fixpoint at
    ``neutral``; ``decay`` in [0, 1].
    """
    return round(weight + (neutral - weight) * decay, 4)


def reweight_from_feedback(edge_rewards: dict[tuple[str, str], float] | None = None) -> int:
    """Recompute RELATED edge weights from structure + optional RAGAS feedback.

    ``edge_rewards`` maps (source, target) entity pairs to a reward in [0, 1] (typically
    the mean RAGAS score of answers whose retrieval used that edge). Edges present in the
    feedback are re-scored from structure+reward; edges *absent* from feedback decay toward
    the neutral 1.0 baseline so stale paths don't ossify. Returns the number of edges
    updated.
    """
    edge_rewards = edge_rewards or {}
    try:
        g, edges = _load_graph()
    except Exception:
        # No graph service (Neo4j down) — nothing to reweight; evaluation scoring
        # still completes so results don't hard-fail.
        return 0
    embeddings = _train_embeddings(g)
    if not embeddings:
        return 0

    updates = []
    for e in edges:
        s, t = e["source"], e["target"]
        touched = (s, t) in edge_rewards or (t, s) in edge_rewards
        if touched:
            structural = (_cosine(embeddings[s], embeddings[t]) + 1) / 2  # → [0, 1]
            reward = edge_rewards.get((s, t), edge_rewards.get((t, s), 0.5))
            alpha = settings.graphsage_alpha  # read per call, not at import
            new_weight = alpha * structural + (1 - alpha) * reward
            # keep weights in a sane positive band for traversal
            new_weight = max(0.05, min(2.0, round(new_weight * 2, 4)))
        else:
            new_weight = _decay_toward_neutral(e["weight"], settings.edge_decay)
        updates.append({"s": s, "t": t, "rt": e["rel_type"], "w": new_weight})

    try:
        with neo4j_driver().session() as session:
            session.run(
                """
                UNWIND $updates AS u
                MATCH (a:Entity {name: u.s})-[r:RELATED {rel_type: u.rt}]->(b:Entity {name: u.t})
                SET r.weight = u.w
                """,
                updates=updates,
            )
    except Exception as exc:
        if _neo4j_down(exc):
            from .fallback_graph import set_edge_weights
            set_edge_weights(updates)
        else:
            raise
    return len(updates)
