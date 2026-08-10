"""Retrieval core: dense search → multi-hop graph expansion → Cohere Rerank.

This is the read path and the heart of the pipeline:

1. Dense search in Pinecone for the top-K candidates.
2. Graph expansion: take the top dense hits as seeds, traverse the knowledge graph
   (multiple hops, weighted) to surface related chunks vector search missed.
3. Merge + dedupe the two candidate sets.
4. Cohere Rerank the merged set, drop passages below a relevance floor, keep top-N.

Note: "graph expansion" is the second retrieval axis here, not lexical/BM25 — this is
dense + graph, not dense + sparse hybrid search.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import numpy as np

from ..config import settings
from ..errors import SearchUnavailable
from . import graphrag, vectorstore
from .clients import EmbeddingUnavailable, cohere_client


def _dedupe(candidates: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for c in candidates:
        cid = c.get("chunk_id")
        if not cid:
            continue
        prev = seen.get(cid)
        # keep the richer record (dense hits carry a score; graph hits carry text)
        if prev is None or (c.get("text") and not prev.get("text")):
            seen[cid] = c
    return list(seen.values())


def _cohere_rerank(question: str, candidates: list[dict], top_n: int) -> list[dict]:
    # Filter candidates to ensure every candidate has a valid non-empty string for 'text'
    valid_candidates = []
    docs = []
    for c in candidates:
        text = c.get("text")
        if text and isinstance(text, str) and text.strip():
            valid_candidates.append(c)
            docs.append(text.strip())

    if not docs:
        return []

    try:
        resp = cohere_client().rerank(
            model=settings.cohere_rerank_model,
            query=question,
            documents=docs,
            top_n=min(top_n, len(docs)),
        )
        ranked: list[dict] = []
        for result in resp.results:
            if result.relevance_score < settings.rerank_min_score:
                continue
            c = dict(valid_candidates[result.index])
            raw_rerank = float(result.relevance_score)
            path_w = c.get("path_weight", 0.0)
            # Graph-Aware Hybrid Fusion: Cohere Rerank + Neo4j Path Weight Bonus
            fused_score = raw_rerank + (settings.graph_fusion_beta * float(np.log1p(path_w)))
            c["score"] = float(fused_score)
            ranked.append(c)

        if not ranked and resp.results:
            for result in resp.results[:3]:
                c = dict(valid_candidates[result.index])
                raw_rerank = float(result.relevance_score)
                path_w = c.get("path_weight", 0.0)
                c["score"] = raw_rerank + (settings.graph_fusion_beta * float(np.log1p(path_w)))
                ranked.append(c)

        if not ranked:
            # Never report "no context found" when real passages were retrieved —
            # e.g. the reranker returned nothing or refused the call. Fall back to
            # the direct (dense + graph) score ordering so the user still gets an answer.
            valid_candidates.sort(key=lambda x: (x.get("score", 0.0) + x.get("path_weight", 0.0)), reverse=True)
            return valid_candidates[:top_n]

        ranked.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        return ranked
    except Exception as exc:
        import logging
        logging.getLogger("app").warning(f"Cohere rerank failed ({exc}), falling back to direct score sorting")
        valid_candidates.sort(key=lambda x: (x.get("score", 0.0) + x.get("path_weight", 0.0)), reverse=True)
        return valid_candidates[:top_n]


def fetch_graph_entity_summaries(question: str, user_id: str) -> list[dict]:
    """Fetch Knowledge Graph entity metadata (rationale & relationships) for entities mentioned in question."""
    candidates = []
    try:
        with graphrag.neo4j_driver().session() as session:
            res = session.run(
                """
                MATCH (e:Entity)
                WHERE (e.user_id = $user_id OR e.user_id IS NULL)
                  AND size(e.name) >= 3
                  AND NOT toLower(e.name) IN ['what', 'how', 'why', 'where', 'when', 'describe', 'explain', 'detail', 'document', 'documents']
                  AND toLower($question) CONTAINS toLower(e.name)
                OPTIONAL MATCH (e)-[r:RELATED]-(neighbor:Entity)
                RETURN e.name AS name,
                       e.type AS type,
                       e.rationale AS rationale,
                       collect(DISTINCT {neighbor: neighbor.name, rel_type: r.rel_type})[..5] AS rels
                LIMIT 5
                """,
                user_id=user_id,
                question=question,
            )
            for record in res:
                name = record.get("name")
                if not name:
                    continue
                etype = record.get("type") or "CONCEPT"
                rationale = record.get("rationale") or f"Domain entity mined from uploaded documents."
                rels = record.get("rels") or []
                rel_parts = []
                for r in rels:
                    if isinstance(r, dict) and r.get("neighbor"):
                        rel_parts.append(f"{r['neighbor']} ({r.get('rel_type', 'RELATED')})")
                rel_str = ", ".join(rel_parts) if rel_parts else "None direct"

                text_content = (
                    f"Knowledge Graph Entity: {name} [{etype}]\n"
                    f"Rationale & Description: {rationale}\n"
                    f"Connected Entities: {rel_str}"
                )
                candidates.append({
                    "chunk_id": f"kg_entity_{name}",
                    "source": f"Knowledge Graph ({name})",
                    "text": text_content,
                    "score": 0.85,
                    "via_graph": True,
                    "path_weight": 0.5,
                })
    except Exception as exc:
        if graphrag._is_neo4j_unavailable(exc):
            from .fallback_graph import graph_entity_summaries
            return graph_entity_summaries(question, user_id)
        import logging
        logging.getLogger("app").warning(f"Failed to fetch graph entity summaries: {exc}")

    return candidates


def fetch_chunks_by_query_entities(question: str, user_id: str) -> list[dict]:
    """Match graph entities mentioned in the query string and fetch their exact source document text chunks."""
    chunk_ids = set()
    try:
        with graphrag.neo4j_driver().session() as session:
            res = session.run(
                """
                MATCH (c:Chunk)-[:MENTIONS]->(e:Entity)
                WHERE (c.user_id = $user_id OR c.user_id IS NULL OR c.user_id = 'guest' OR $user_id = 'guest')
                  AND size(e.name) >= 3
                  AND NOT toLower(e.name) IN ['what', 'how', 'why', 'where', 'when', 'describe', 'explain', 'detail', 'document', 'documents']
                  AND toLower($question) CONTAINS toLower(e.name)
                RETURN DISTINCT c.chunk_id AS chunk_id
                LIMIT 10
                """,
                user_id=user_id,
                question=question,
            )
            chunk_ids = {r["chunk_id"] for r in res if r.get("chunk_id")}
    except Exception as exc:
        if graphrag._is_neo4j_unavailable(exc):
            from .fallback_graph import chunks_by_query_entities
            chunk_ids = chunks_by_query_entities(question, user_id)

    if not chunk_ids:
        return []
    return vectorstore.fetch_by_ids(list(chunk_ids))


def retrieve(question: str, top_k: int | None = None, use_graph: bool = True, user_id: str | None = None) -> list[dict]:
    """Return the reranked top-N candidate chunks for a question."""
    return retrieve_with_trace(question, top_k=top_k, use_graph=use_graph, user_id=user_id)[0]


def retrieve_with_trace(
    question: str, top_k: int | None = None, use_graph: bool = True, user_id: str | None = None, version: str | None = None
) -> tuple[list[dict], list[tuple[str, str]]]:
    """Retrieve scoped by user_id, and also report which RELATED edges fed the final answer context.

    ``version`` (shadow) keeps isolation through both the dense and graph paths;
    ``None`` is the live path and is byte-identical to before.
    """
    top_k = top_k or settings.retrieve_top_k
    target_user = user_id or "guest"

    dense: list[dict] = []
    entity_chunks: list[dict] = []
    graph_summaries: list[dict] = []

    with ThreadPoolExecutor(max_workers=3) as pool:
        dense_future = pool.submit(vectorstore.query, question, top_k, target_user, version)
        entity_future = pool.submit(fetch_chunks_by_query_entities, question, target_user)
        graph_summary_future = pool.submit(fetch_graph_entity_summaries, question, target_user)

        try:
            dense = dense_future.result() or []
        except EmbeddingUnavailable:
            # No query vector means no retrieval; surface it rather than answering from nothing.
            raise
        except SearchUnavailable:
            # Vector infra is down — surface it rather than letting the graph-only path
            # render the failure as "no relevant context".
            raise
        except Exception as exc:
            import logging
            logging.getLogger("app").warning(f"Dense vector search failed safely: {exc}")

        try:
            entity_chunks = entity_future.result() or []
        except Exception as exc:
            import logging
            logging.getLogger("app").warning(f"Entity chunk search failed safely: {exc}")

        try:
            graph_summaries = graph_summary_future.result() or []
        except Exception as exc:
            import logging
            logging.getLogger("app").warning(f"Graph summary search failed safely: {exc}")

    # 3. Graph expansion from dense & entity seeds
    graph_hits: list[dict] = []
    edges_by_chunk: dict[str, list[tuple[str, str]]] = {}
    if use_graph:
        try:
            all_seeds = _dedupe(dense + entity_chunks)
            seed_ids = [c["chunk_id"] for c in all_seeds[: min(5, len(all_seeds))] if c.get("chunk_id")]
            if seed_ids:
                expansions = graphrag.expand(seed_ids, limit=min(3, top_k // 2), user_id=target_user, question=question, version=version)
                path_weight_map = {e["chunk_id"]: e.get("path_weight", 0.0) for e in expansions if e.get("chunk_id")}
                for e in expansions:
                    cid = e.get("chunk_id")
                    if cid:
                        raw_edges = e.get("edges", [])
                        valid_edges = []
                        for edge in raw_edges:
                            if isinstance(edge, (list, tuple)) and len(edge) >= 2 and edge[0] and edge[1]:
                                valid_edges.append((str(edge[0]), str(edge[1])))
                        edges_by_chunk[cid] = valid_edges

                valid_exp_ids = list(path_weight_map.keys())
                if valid_exp_ids:
                    raw_graph_hits = vectorstore.fetch_by_ids(valid_exp_ids)
                    for gh in raw_graph_hits:
                        if gh.get("chunk_id"):
                            gh["path_weight"] = path_weight_map.get(gh["chunk_id"], 0.0)
                            gh["via_graph"] = True
                            graph_hits.append(gh)
        except Exception as exc:
            import logging
            logging.getLogger("app").warning(f"Graph expansion retrieval failed safely: {exc}")

    # 4. Merge + dedupe candidates
    merged = _dedupe(dense + entity_chunks + graph_summaries + graph_hits)

    # 5. Rerank with Graph Fusion
    ranked = _cohere_rerank(question, merged, top_n=settings.rerank_top_n)

    # 6. Collect surviving edges
    surviving_edges: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for c in ranked:
        cid = c.get("chunk_id")
        if cid:
            for edge in edges_by_chunk.get(cid, []):
                if isinstance(edge, (list, tuple)) and len(edge) >= 2 and edge[0] and edge[1]:
                    key = (str(edge[0]), str(edge[1]))
                    if key not in seen:
                        seen.add(key)
                        surviving_edges.append(key)

    return ranked, surviving_edges
