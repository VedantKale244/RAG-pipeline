"""SQLite-backed knowledge-graph store — drop-in mirror of the Neo4j layer.

Used automatically whenever Neo4j is unreachable (see ``graphrag._is_neo4j_unavailable``).
The schema mirrors the Neo4j model 1:1:

    chunks:   (chunk_id, source, document_id, user_id, text, selfopt_version)
    entities: (name, type, rationale, embedding_json, aliases_json, user_id)
    mentions: (chunk_id, entity_name)           -- :Chunk-[:MENTIONS]->:Entity
    related:  (source, target, rel_type, weight, user_id)  -- :Entity-[:RELATED]->:Entity
    summaries:(user_id, summary_json)

Entity identity is global by exact ``name`` (like the Neo4j uniqueness
constraint); user scoping flows through chunk→mention edges exactly as it does
in Cypher. Every function here returns the same shapes ``graphrag.py``'s pure
helpers expect, so the two backends share one rendering pipeline.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from pathlib import Path

logger = logging.getLogger("app")

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_DB_PATH = _DATA_DIR / "graph.db"

# Mirrors retrieval.py's block-list used in the Neo4j entity-survey query.
_STOP_ENTITY_NAMES = {
    "what", "how", "why", "where", "when", "describe", "explain",
    "detail", "document", "documents",
}


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _canon(name: str) -> str:
    """Lowercase + collapse-whitespace canonicalisation (alias table omitted)."""
    return re.sub(r"\s+", " ", (name or "").strip()).lower()


def _embedding_json(emb) -> str | None:
    if emb is None:
        return None
    return json.dumps([float(x) for x in emb])


def _embedding_from(row_emb) -> list[float] | None:
    if not row_emb:
        return None
    try:
        return list(json.loads(row_emb))
    except Exception:
        return None


def _aliases_json(aliases) -> str:
    return json.dumps([a for a in aliases or [] if a])


def _aliases_from(row_aliases) -> list[str]:
    if not row_aliases:
        return []
    try:
        return list(json.loads(row_aliases))
    except Exception:
        return []


_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS chunks (
        chunk_id TEXT PRIMARY KEY,
        source TEXT,
        document_id TEXT,
        user_id TEXT,
        text TEXT,
        selfopt_version TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS entities (
        name TEXT PRIMARY KEY,
        type TEXT,
        rationale TEXT,
        embedding TEXT,
        aliases TEXT,
        user_id TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mentions (
        chunk_id TEXT NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
        entity_name TEXT NOT NULL REFERENCES entities(name) ON DELETE CASCADE,
        PRIMARY KEY (chunk_id, entity_name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS related (
        source TEXT NOT NULL REFERENCES entities(name) ON DELETE CASCADE,
        target TEXT NOT NULL REFERENCES entities(name) ON DELETE CASCADE,
        rel_type TEXT NOT NULL,
        weight REAL DEFAULT 1.0,
        user_id TEXT,
        PRIMARY KEY (source, target, rel_type)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS summaries (
        user_id TEXT PRIMARY KEY,
        summary_json TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_chunks_user ON chunks(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(document_id)",
    "CREATE INDEX IF NOT EXISTS idx_mentions_entity ON mentions(entity_name)",
    "CREATE INDEX IF NOT EXISTS idx_related_source ON related(source)",
    "CREATE INDEX IF NOT EXISTS idx_related_target ON related(target)",
]


def ensure_schema() -> None:
    with _db() as conn:
        for stmt in _SCHEMA:
            conn.execute(stmt)


def _prune_orphan_entities(conn: sqlite3.Connection) -> int:
    """Delete entities that no chunk mentions (mirrors Cypher orphan prune)."""
    cur = conn.execute(
        "DELETE FROM entities WHERE NOT EXISTS "
        "(SELECT 1 FROM mentions WHERE mentions.entity_name = entities.name)"
    )
    return cur.rowcount or 0


# --- Build path ---------------------------------------------------------------

def load_existing_entities(user_id: str) -> dict[str, dict]:
    """Entities reachable by this user's chunks, keyed by canonical name.

    Shape mirrors graphrag._load_existing_entities: values are
    {"canonical_name", "aliases", "embedding"}.
    """
    from .graphrag import _canonicalize

    existing: dict[str, dict] = {}
    with _db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT e.name AS name, e.aliases AS aliases, e.embedding AS embedding "
            "FROM entities e "
            "JOIN mentions m ON m.entity_name = e.name "
            "JOIN chunks c ON c.chunk_id = m.chunk_id "
            "WHERE c.user_id = ?",
            (user_id,),
        ).fetchall()
    for r in rows:
        name = r["name"]
        key = _canonicalize(name)
        existing[key] = {
            "canonical_name": re.sub(r"[\r\n\t]+", " ", name).strip(),
            "aliases": [_canonicalize(a) for a in _aliases_from(r["aliases"]) if a],
            "embedding": _embedding_from(r["embedding"]),
        }
    return existing


def get_existing_chunk_ids(chunk_ids: list[str], user_id: str) -> set[str]:
    if not chunk_ids or not user_id:
        return set()
    with _db() as conn:
        ph = ",".join("?" for _ in chunk_ids)
        rows = conn.execute(
            f"SELECT chunk_id FROM chunks WHERE chunk_id IN ({ph}) AND user_id = ?",
            (*chunk_ids, user_id),
        ).fetchall()
    return {r["chunk_id"] for r in rows}


def _upsert_chunk(conn: sqlite3.Connection, rec: dict) -> None:
    conn.execute(
        "INSERT INTO chunks (chunk_id, source, document_id, user_id, text, selfopt_version) "
        "VALUES (?, ?, ?, ?, ?, NULL) "
        "ON CONFLICT(chunk_id) DO UPDATE SET "
        "  source = excluded.source, document_id = excluded.document_id, "
        "  user_id = excluded.user_id, text = excluded.text",
        (rec["chunk_id"], rec.get("source"), rec.get("document_id"),
         rec.get("user_id"), rec.get("text", "")),
    )


def _upsert_entity(conn: sqlite3.Connection, ent: dict) -> None:
    conn.execute(
        "INSERT INTO entities (name, type, rationale, embedding, aliases, user_id) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(name) DO UPDATE SET "
        "  type = COALESCE(excluded.type, entities.type), "
        "  rationale = COALESCE(excluded.rationale, entities.rationale), "
        "  embedding = COALESCE(excluded.embedding, entities.embedding), "
        "  aliases = COALESCE(excluded.aliases, entities.aliases), "
        "  user_id = COALESCE(entities.user_id, excluded.user_id)",
        (ent["name"], ent.get("type", "CONCEPT"), ent.get("rationale"),
         _embedding_json(ent.get("embedding")), _aliases_json(ent.get("aliases")),
         ent.get("user_id")),
    )


def _add_mention(conn: sqlite3.Connection, chunk_id: str, entity_name: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO mentions (chunk_id, entity_name) VALUES (?, ?)",
        (chunk_id, entity_name),
    )


def _add_related(conn: sqlite3.Connection, rel: dict, user_id: str) -> None:
    conn.execute(
        "INSERT INTO related (source, target, rel_type, weight, user_id) "
        "VALUES (?, ?, ?, 1.0, ?) "
        "ON CONFLICT(source, target, rel_type) DO NOTHING",
        (rel["source"], rel["target"], rel.get("rel_type", "RELATED"), user_id),
    )


def persist_build(write_records: list[dict], alias_updates: list[tuple], user_id: str) -> None:
    """Apply validated chunk/entity/relationship writes in one transaction.

    Mirrors the Neo4j ``_WRITE_CYPHER`` merge semantics (existing entities keep
    type/rationale, relationship weight only set on create).
    """
    ensure_schema()
    with _db() as conn:
        for rec in write_records:
            _upsert_chunk(conn, rec)
            entities = rec.get("entities") or []
            relationships = rec.get("relationships") or []
            written = {e.get("name") for e in entities}
            for ent in entities:
                _upsert_entity(conn, ent)
                _add_mention(conn, rec["chunk_id"], ent["name"])
            for rel in relationships:
                for end in (rel["source"], rel["target"]):
                    if end not in written:
                        _upsert_entity(conn, {"name": end, "type": "OTHER", "rationale": None})
                _add_related(conn, rel, rec.get("user_id", user_id))
        # Alias merges reference entities that must already exist (Neo4j's
        # _merge_entity_alias MATCHes the canonical node), so apply them last.
        for canonical_name, alias_name, _uid in alias_updates:
            row = conn.execute(
                "SELECT aliases FROM entities WHERE name = ?", (canonical_name,)
            ).fetchone()
            aliases = _aliases_from(row["aliases"] if row else None)
            if alias_name not in aliases:
                aliases.append(alias_name)
                conn.execute(
                    "UPDATE entities SET aliases = ? WHERE name = ?",
                    (_aliases_json(aliases), canonical_name),
                )


# --- Summary -----------------------------------------------------------------

def aggregate_graph_data(user_id: str) -> dict:
    """Mirror graphrag._aggregate_graph_data for the summary LLM."""
    with _db() as conn:
        ent_rows = conn.execute(
            "SELECT DISTINCT e.name AS name, e.type AS type, e.rationale AS rationale "
            "FROM mentions m "
            "JOIN chunks c ON c.chunk_id = m.chunk_id AND c.user_id = ? "
            "JOIN entities e ON e.name = m.entity_name",
            (user_id,),
        ).fetchall()
        rel_rows = conn.execute(
            "SELECT DISTINCT r.source AS source, r.target AS target, r.rel_type AS rel_type "
            "FROM related r "
            "JOIN mentions ma ON ma.entity_name = r.source "
            "JOIN chunks ca ON ca.chunk_id = ma.chunk_id AND ca.user_id = ? "
            "JOIN mentions mb ON mb.entity_name = r.target "
            "JOIN chunks cb ON cb.chunk_id = mb.chunk_id AND cb.user_id = ?",
            (user_id, user_id),
        ).fetchall()

    entities = {
        r["name"]: {"type": r["type"], "rationale": r["rationale"], "degree": 0, "relations": []}
        for r in ent_rows
    }
    relationships = []
    for r in rel_rows:
        s, t, rt = r["source"], r["target"], r["rel_type"]
        relationships.append((s, t, rt))
        if s in entities:
            entities[s]["degree"] += 1
            entities[s]["relations"].append({"target": t, "type": rt})
        if t in entities:
            entities[t]["degree"] += 1
    return {"entities": entities, "relationships": relationships}


def save_summary(user_id: str, summary_json_str: str) -> None:
    ensure_schema()
    with _db() as conn:
        conn.execute(
            "INSERT INTO summaries (user_id, summary_json) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET summary_json = excluded.summary_json",
            (user_id, summary_json_str),
        )


def get_stored_summary(user_id: str) -> dict | None:
    with _db() as conn:
        row = conn.execute(
            "SELECT summary_json FROM summaries WHERE user_id = ?", (user_id,)
        ).fetchone()
    if not row or not row["summary_json"]:
        return None
    try:
        return json.loads(row["summary_json"])
    except Exception:
        return None


def summary_counts(user_id: str) -> tuple[int, int, list[dict], dict]:
    """(total_entities, total_relationships, top_hubs, entity_types)."""
    with _db() as conn:
        ent_row = conn.execute(
            "SELECT count(DISTINCT m.entity_name) AS cnt "
            "FROM mentions m JOIN chunks c ON c.chunk_id = m.chunk_id AND c.user_id = ?",
            (user_id,),
        ).fetchone()
        rel_row = conn.execute(
            "SELECT count(DISTINCT r.source || '|' || r.target || '|' || r.rel_type) AS cnt FROM related r "
            "JOIN mentions ma ON ma.entity_name = r.source "
            "JOIN chunks ca ON ca.chunk_id = ma.chunk_id AND ca.user_id = ? "
            "JOIN mentions mb ON mb.entity_name = r.target "
            "JOIN chunks cb ON cb.chunk_id = mb.chunk_id AND cb.user_id = ?",
            (user_id, user_id),
        ).fetchone()
        hub_rows = conn.execute(
            "SELECT e.name AS name, count(DISTINCT r.source || '|' || r.target || '|' || r.rel_type) AS degree "
            "FROM mentions m "
            "JOIN chunks c ON c.chunk_id = m.chunk_id AND c.user_id = ? "
            "JOIN entities e ON e.name = m.entity_name "
            "JOIN related r ON r.source = e.name OR r.target = e.name "
            "GROUP BY e.name ORDER BY degree DESC LIMIT 5",
            (user_id,),
        ).fetchall()
        type_rows = conn.execute(
            "SELECT coalesce(e.type, 'CONCEPT') AS type, count(DISTINCT m.entity_name) AS count "
            "FROM mentions m "
            "JOIN chunks c ON c.chunk_id = m.chunk_id AND c.user_id = ? "
            "JOIN entities e ON e.name = m.entity_name "
            "GROUP BY e.type",
            (user_id,),
        ).fetchall()

    top_hubs = [{"name": r["name"], "degree": int(r["degree"])} for r in hub_rows]
    entity_types = {r["type"]: int(r["count"]) for r in type_rows}
    return int(ent_row["cnt"]), int(rel_row["cnt"]), top_hubs, entity_types


# --- Deletion ----------------------------------------------------------------

def _delete_chunks_scope(where_clause: str, params: tuple) -> int:
    ensure_schema()
    with _db() as conn:
        row = conn.execute(f"SELECT count(*) AS cnt FROM chunks WHERE {where_clause}", params).fetchone()
        count = int(row["cnt"]) if row else 0
        conn.execute(f"DELETE FROM chunks WHERE {where_clause}", params)
        _prune_orphan_entities(conn)
    return count


def delete_by_document(document_id: str) -> dict:
    if not document_id:
        return {"chunks": 0}
    n = _delete_chunks_scope("document_id = ?", (document_id,))
    return {"chunks": n}


def delete_by_user(user_id: str) -> dict:
    if not user_id:
        return {"chunks": 0}
    n = _delete_chunks_scope("user_id = ?", (user_id,))
    return {"chunks": n}


def purge_user_knowledge(user_id: str) -> dict:
    if not user_id:
        return {"chunks": 0}
    n = _delete_chunks_scope("user_id = ?", (user_id,))
    with _db() as conn:
        conn.execute("DELETE FROM summaries WHERE user_id = ?", (user_id,))
    return {"chunks": n}


def delete_shadow(version: str) -> dict:
    if not version:
        return {"chunks": 0}
    n = _delete_chunks_scope("selfopt_version = ?", (version,))
    return {"chunks": n}


def purge_invalid_entities_from_db() -> int:
    from .graphrag import _is_valid_entity

    ensure_schema()
    deleted = 0
    with _db() as conn:
        _prune_orphan_entities(conn)
        rows = conn.execute("SELECT name FROM entities").fetchall()
        invalid = [r["name"] for r in rows if not _is_valid_entity(r["name"])]
        if invalid:
            ph = ",".join("?" for _ in invalid)
            cur = conn.execute(f"DELETE FROM entities WHERE name IN ({ph})", invalid)
            deleted = cur.rowcount or 0
    return deleted


def is_document_graph_built(document_id: str, user_id: str) -> bool:
    if not document_id or not user_id:
        return False
    with _db() as conn:
        row = conn.execute(
            "SELECT count(*) AS cnt FROM chunks WHERE document_id = ? AND user_id = ?",
            (document_id, user_id),
        ).fetchone()
    return bool(row and row["cnt"] > 0)


# --- Reads for the shared rendering pipeline ---------------------------------

def graph_snapshot_data(limit: int, user_id: str) -> tuple[list[dict], list[str], dict, dict]:
    """(edges, valid_nodes, doc_entity_map, doc_title_map) for graphrag.graph_snapshot."""
    with _db() as conn:
        edge_rows = conn.execute(
            "SELECT DISTINCT r.source AS source, r.target AS target, "
            "       r.rel_type AS rel_type, r.weight AS weight "
            "FROM related r "
            "JOIN mentions ma ON ma.entity_name = r.source "
            "JOIN chunks ca ON ca.chunk_id = ma.chunk_id AND ca.user_id = ? "
            "JOIN mentions mb ON mb.entity_name = r.target "
            "JOIN chunks cb ON cb.chunk_id = mb.chunk_id AND cb.user_id = ? "
            "LIMIT ?",
            (user_id, user_id, limit),
        ).fetchall()
        node_rows = conn.execute(
            "SELECT DISTINCT m.entity_name AS name FROM mentions m "
            "JOIN chunks c ON c.chunk_id = m.chunk_id AND c.user_id = ?",
            (user_id,),
        ).fetchall()
        doc_rows = conn.execute(
            "SELECT DISTINCT c.document_id AS doc_id, "
            "       coalesce(c.source, c.document_id) AS doc_title, m.entity_name AS name "
            "FROM mentions m JOIN chunks c ON c.chunk_id = m.chunk_id AND c.user_id = ?",
            (user_id,),
        ).fetchall()

    edges = [dict(r) for r in edge_rows]
    valid_nodes = sorted({r["name"] for r in node_rows})

    doc_entity_map: dict[str, set[str]] = {}
    doc_title_map: dict[str, str] = {}
    for r in doc_rows:
        doc_id, name = r["doc_id"], r["name"]
        if not doc_id or not name:
            continue
        doc_entity_map.setdefault(doc_id, set()).add(name)
        doc_title_map[doc_id] = r["doc_title"] or doc_id

    return edges, valid_nodes, doc_entity_map, doc_title_map


def expand_rows(
    seed_ids: list[str],
    hops: int,
    user_id: str,
    max_paths: int,
    version: str | None,
) -> list[dict]:
    """Weighted RELATED traversal returning rows shaped like the Neo4j expand query."""
    with _db() as conn:
        seed_rows = conn.execute(
            "SELECT DISTINCT m.entity_name AS name FROM mentions m "
            "JOIN chunks c ON c.chunk_id = m.chunk_id "
            "WHERE c.chunk_id IN (%s) AND c.user_id = ?" % ",".join("?" for _ in seed_ids),
            (*seed_ids, user_id),
        ).fetchall()
        edge_rows = conn.execute(
            "SELECT source, target, rel_type, weight FROM related"
        ).fetchall()
        emb_rows = conn.execute("SELECT name, embedding FROM entities").fetchall()

    seed_entities = {r["name"] for r in seed_rows}
    if not seed_entities:
        return []

    adjacency: dict[str, list[tuple[str, float]]] = {}
    for r in edge_rows:
        w = float(r["weight"] or 1.0)
        adjacency.setdefault(r["source"], []).append((r["target"], w))
        adjacency.setdefault(r["target"], []).append((r["source"], w))

    emb_lookup = {r["name"]: _embedding_from(r["embedding"]) for r in emb_rows}

    # BFS up to `hops` RELATED edges, keeping the highest-score path per (entity, depth).
    best: dict[tuple[str, int], tuple[float, list[tuple], list[str]]] = {}
    frontier: list[tuple[str, float, list[tuple], list[str]]] = [
        (e, 1.0, [], [e]) for e in seed_entities
    ]
    for depth in range(1, int(hops) + 1):
        next_frontier: list[tuple[str, float, list[tuple], list[str]]] = []
        for node, score, edges, nodes in frontier:
            for nbr, w in adjacency.get(node, ()) or []:
                new_score = score * w
                new_edges = edges + [(node, nbr)]
                new_nodes = nodes + [nbr]
                key = (nbr, depth)
                if key not in best or new_score > best[key][0]:
                    best[key] = (new_score, new_edges, new_nodes)
                next_frontier.append((nbr, new_score, new_edges, new_nodes))
        frontier = next_frontier
        if not frontier:
            break

    if not best:
        return []

    version_clause = "AND c.selfopt_version IS NULL" if version is None else "AND c.selfopt_version = ?"
    version_param = () if version is None else (version,)

    rows: list[dict] = []
    with _db() as conn:
        for (entity, _depth), (score, edges, nodes) in best.items():
            chunk_rows = conn.execute(
                "SELECT DISTINCT c.chunk_id AS chunk_id FROM mentions m "
                "JOIN chunks c ON c.chunk_id = m.chunk_id "
                "WHERE m.entity_name = ? AND c.user_id = ? "
                f"AND c.chunk_id NOT IN ({','.join('?' for _ in seed_ids)}) {version_clause}",
                (entity, user_id, *seed_ids, *version_param),
            ).fetchall()
            for cr in chunk_rows:
                rows.append({
                    "chunk_id": cr["chunk_id"],
                    "path_score": score,
                    "path_edges": [list(e) for e in edges],
                    "path_nodes": [{"name": n, "embedding": emb_lookup.get(n)} for n in nodes],
                })

    rows.sort(key=lambda r: float(r["path_score"]), reverse=True)
    return rows[: max_paths]


# --- Entity details (with auto-repair parity) ---------------------------------

def entity_details(raw_name: str, clean_name: str, user_id: str) -> dict:
    """Mirror graphrag.get_entity_details against SQLite, including the two auto-repairs."""
    target_user = user_id
    matched_name = _find_entity_name(raw_name, clean_name)

    with _db() as conn:
        if matched_name:
            info = conn.execute(
                "SELECT name, type, rationale FROM entities WHERE name = ?", (matched_name,)
            ).fetchone()
            ent_type = (info["type"] or "CONCEPT") if info else "CONCEPT"
            ent_rationale = info["rationale"] if info and info["rationale"] else ""
        else:
            ent_type = "CONCEPT"
            ent_rationale = ""

        # Mentioning chunks
        chunk_rows = conn.execute(
            "SELECT DISTINCT c.chunk_id AS chunk_id, c.source AS source, c.text AS text "
            "FROM mentions m JOIN chunks c ON c.chunk_id = m.chunk_id AND c.user_id = ? "
            "WHERE m.entity_name = ? LIMIT 10",
            (target_user, matched_name),
        ).fetchall() if matched_name else []
        passages = [dict(r) for r in chunk_rows]

        # Connected relationships
        rel_rows = conn.execute(
            "SELECT source, target, rel_type, weight FROM related "
            "WHERE source = ? OR target = ? LIMIT 30",
            (matched_name, matched_name),
        ).fetchall() if matched_name else []
        relationships = []
        for r in rel_rows:
            neighbor = r["target"] if r["source"] == matched_name else r["source"]
            if neighbor.lower() == raw_name.lower():
                continue
            relationships.append({
                "neighbor": neighbor,
                "rel_type": r["rel_type"],
                "weight": float(r["weight"]),
            })

        # AUTO-REPAIR 1: co-occurring neighbors from shared chunks.
        if not relationships and passages and matched_name:
            co_rows = conn.execute(
                "SELECT DISTINCT m2.entity_name AS neighbor "
                "FROM mentions m1 "
                "JOIN mentions m2 ON m2.chunk_id = m1.chunk_id "
                "JOIN chunks c ON c.chunk_id = m1.chunk_id AND c.user_id = ? "
                "WHERE m1.entity_name = ? AND m2.entity_name <> ? LIMIT 15",
                (target_user, matched_name, matched_name),
            ).fetchall()
            found = [r["neighbor"] for r in co_rows if r["neighbor"].lower() != raw_name.lower()]
            for n_name in found:
                relationships.append({"neighbor": n_name, "rel_type": "CO_OCCURS", "weight": 0.85})
                conn.execute(
                    "INSERT INTO related (source, target, rel_type, weight, user_id) "
                    "VALUES (?, ?, 'CO_OCCURS', 0.85, ?) "
                    "ON CONFLICT(source, target, rel_type) DO NOTHING",
                    (matched_name, n_name, target_user),
                )

        # AUTO-REPAIR 2: enrich generic/missing rationale.
        is_generic = (
            not ent_rationale
            or "essential domain concept" in ent_rationale.lower()
            or "essential domain entity" in ent_rationale.lower()
        )
        if is_generic and matched_name:
            connected_names = [r["neighbor"] for r in relationships[:3]]
            conn_str = f" connected to {', '.join(connected_names)}" if connected_names else ""
            passage_text = (passages[0]["text"] if passages and passages[0].get("text") else "")
            passage_snippet = passage_text[:160].replace("\n", " ").strip() if passage_text else ""
            if passage_snippet:
                ent_rationale = (
                    f"Key {ent_type.lower()} entity '{raw_name}' mined from document "
                    f"'{passages[0]['source']}'{conn_str}. Domain context: \"{passage_snippet}...\""
                )
            else:
                ent_rationale = (
                    f"Core technical {ent_type.lower()} entity '{raw_name}'{conn_str} "
                    "indexed for GraphRAG multi-hop retrieval and reasoning."
                )
            conn.execute("UPDATE entities SET rationale = ? WHERE name = ?", (ent_rationale, matched_name))

    return {
        "name": raw_name,
        "type": ent_type,
        "rationale": ent_rationale,
        "relationships": relationships,
        "passages": passages,
    }


def _find_entity_name(raw_name: str, clean_name: str) -> str | None:
    """Locate a stored entity by exact name or lowercase alias."""
    raw_l = raw_name.lower()
    with _db() as conn:
        rows = conn.execute("SELECT name, aliases FROM entities").fetchall()
    for r in rows:
        if r["name"].lower() == raw_l or r["name"].lower() == clean_name.lower():
            return r["name"]
    for r in rows:
        if clean_name.lower() in [a.lower() for a in _aliases_from(r["aliases"])]:
            return r["name"]
    return None


# --- Retrieval surveys -------------------------------------------------------

def graph_entity_summaries(question: str, user_id: str) -> list[dict]:
    """Entities mentioned in the question plus their neighbour relationships."""
    q = (question or "").lower()
    with _db() as conn:
        rows = conn.execute(
            "SELECT e.name AS name, e.type AS type, e.rationale AS rationale "
            "FROM entities e WHERE (e.user_id = ? OR e.user_id IS NULL) "
            "AND length(e.name) >= 3",
            (user_id,),
        ).fetchall()
    out = []
    for r in rows:
        name = r["name"]
        if len(name) < 3 or name.lower() in _STOP_ENTITY_NAMES:
            continue
        if q and name.lower() not in q:
            continue
        rel_rows = _neighbors(name)
        rel_parts = [f"{n} ({rt})" for n, rt in rel_rows[:5]]
        rel_str = ", ".join(rel_parts) if rel_parts else "None direct"
        rationale = r["rationale"] or f"Domain entity mined from uploaded documents."
        text_content = (
            f"Knowledge Graph Entity: {name} [{r['type'] or 'CONCEPT'}]\n"
            f"Rationale & Description: {rationale}\n"
            f"Connected Entities: {rel_str}"
        )
        out.append({
            "chunk_id": f"kg_entity_{name}",
            "source": f"Knowledge Graph ({name})",
            "text": text_content,
            "score": 0.85,
            "via_graph": True,
            "path_weight": 0.5,
        })
    return out[:5]


def _neighbors(name: str, limit: int = 5) -> list[tuple[str, str]]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT source, target, rel_type FROM related "
            "WHERE source = ? OR target = ? LIMIT ?",
            (name, name, limit),
        ).fetchall()
    out = []
    for r in rows:
        nbr = r["target"] if r["source"] == name else r["source"]
        if nbr:
            out.append((nbr, r["rel_type"]))
    return out


def chunks_by_query_entities(question: str, user_id: str) -> set[str]:
    q = (question or "").lower()
    with _db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT c.chunk_id AS chunk_id "
            "FROM chunks c JOIN mentions m ON m.chunk_id = c.chunk_id "
            "JOIN entities e ON e.name = m.entity_name "
            "WHERE (c.user_id = ? OR c.user_id IS NULL OR c.user_id = 'guest' OR ? = 'guest') "
            "AND length(e.name) >= 3 LIMIT 10",
            (user_id, user_id),
        ).fetchall()
    out = set()
    for r in rows:
        name = r["chunk_id"] and _chunk_has_entity(r["chunk_id"], q)
        if name:
            out.add(r["chunk_id"])
    return out


def _chunk_has_entity(chunk_id: str, q: str) -> bool:
    with _db() as conn:
        rows = conn.execute(
            "SELECT e.name AS name FROM mentions m JOIN entities e ON e.name = m.entity_name "
            "WHERE m.chunk_id = ?",
            (chunk_id,),
        ).fetchall()
    for r in rows:
        name = r["name"]
        if len(name) >= 3 and name.lower() not in _STOP_ENTITY_NAMES and name.lower() in q:
            return True
    return False


# --- Admin stats -------------------------------------------------------------

def admin_stats() -> tuple[list[dict], int, int, int]:
    """(docs, total_chunks, total_nodes, total_edges) mirroring api.admin._get_admin_stats."""
    ensure_schema()
    with _db() as conn:
        doc_rows = conn.execute(
            "SELECT coalesce(source, 'Unknown') AS source, document_id, count(*) AS chunk_count "
            "FROM chunks GROUP BY document_id, source ORDER BY document_id"
        ).fetchall()
        node_row = conn.execute("SELECT count(*) AS cnt FROM entities").fetchone()
        edge_row = conn.execute("SELECT count(*) AS cnt FROM related").fetchone()
    docs = [
        {"source": r["source"], "document_id": r["document_id"], "chunk_count": int(r["chunk_count"])}
        for r in doc_rows
    ]
    total_chunks = sum(int(r["chunk_count"]) for r in doc_rows)
    total_nodes = int(node_row["cnt"]) if node_row else 0
    total_edges = int(edge_row["cnt"]) if edge_row else 0
    return docs, total_chunks, total_nodes, total_edges


def admin_documents() -> dict:
    """Per-user upload graph: documents grouped by user with chunk/entity counts.

    Returns ``{documents: [...], totals: {...}}`` where each document carries
    user_id, source (filename), document_id, chunk_count, entity_count and the
    selfopt version shadowing it (``None`` for live chunks).
    """
    ensure_schema()
    with _db() as conn:
        rows = conn.execute(
            "SELECT c.user_id, c.source, c.document_id, "
            "       count(DISTINCT c.chunk_id) AS chunk_count, "
            "       count(DISTINCT m.entity_name) AS entity_count, "
            "       max(c.selfopt_version) AS selfopt_version "
            "FROM chunks c LEFT JOIN mentions m ON m.chunk_id = c.chunk_id "
            "GROUP BY c.document_id, c.source, c.user_id "
            "ORDER BY c.user_id, c.source"
        ).fetchall()
        ent_row = conn.execute("SELECT count(*) AS cnt FROM entities").fetchone()
        rel_row = conn.execute("SELECT count(*) AS cnt FROM related").fetchone()
        sum_row = conn.execute("SELECT count(*) AS cnt FROM summaries").fetchone()

    documents = [
        {
            "user_id": r["user_id"],
            "source": r["source"] or "Unknown",
            "document_id": r["document_id"],
            "chunk_count": int(r["chunk_count"]),
            "entity_count": int(r["entity_count"]),
            "selfopt_version": r["selfopt_version"],
        }
        for r in rows
    ]
    return {
        "documents": documents,
        "totals": {
            "documents": len(documents),
            "chunks": sum(int(r["chunk_count"]) for r in rows),
            "entities": int(ent_row["cnt"]) if ent_row else 0,
            "relationships": int(rel_row["cnt"]) if rel_row else 0,
            "summaries": int(sum_row["cnt"]) if sum_row else 0,
        },
    }


def admin_users_graph_stats() -> dict[str, dict]:
    """Per-user document/chunk/entity aggregates for the admin users table."""
    ensure_schema()
    out: dict[str, dict] = {}
    with _db() as conn:
        rows = conn.execute(
            "SELECT c.user_id, "
            "       count(DISTINCT c.document_id) AS document_count, "
            "       count(DISTINCT c.chunk_id) AS chunk_count, "
            "       count(DISTINCT m.entity_name) AS entity_count "
            "FROM chunks c LEFT JOIN mentions m ON m.chunk_id = c.chunk_id "
            "WHERE c.user_id IS NOT NULL "
            "GROUP BY c.user_id"
        ).fetchall()
    for r in rows:
        out[r["user_id"]] = {
            "document_count": int(r["document_count"]),
            "chunk_count": int(r["chunk_count"]),
            "entity_count": int(r["entity_count"]),
        }
    return out


# --- Adaptive reweighting ----------------------------------------------------

def load_graph_edges() -> tuple[object, list[dict]]:
    """(networkx.Graph, edges) for adaptive._load_graph."""
    import networkx as nx

    g = nx.Graph()
    edges: list[dict] = []
    with _db() as conn:
        rows = conn.execute("SELECT source, target, rel_type, weight FROM related").fetchall()
    for r in rows:
        g.add_node(r["source"])
        g.add_node(r["target"])
        g.add_edge(r["source"], r["target"])
        edges.append({
            "source": r["source"],
            "target": r["target"],
            "rel_type": r["rel_type"],
            "weight": float(r["weight"] or 1.0),
        })
    return g, edges


def set_edge_weights(updates: list[dict]) -> None:
    ensure_schema()
    with _db() as conn:
        for u in updates:
            conn.execute(
                "UPDATE related SET weight = ? WHERE source = ? AND target = ? AND rel_type = ?",
                (float(u["w"]), u["s"], u["t"], u["rt"]),
            )


def edge_count() -> int:
    with _db() as conn:
        row = conn.execute("SELECT count(*) AS cnt FROM related").fetchone()
    return int(row["cnt"]) if row else 0


def clear_user_graph(user_id: str) -> None:
    """Clear all graph nodes and edges for a user in the SQLite fallback graph."""
    if not user_id:
        return
    ensure_schema()
    with _db() as conn:
        conn.execute("DELETE FROM mentions WHERE chunk_id IN (SELECT chunk_id FROM chunks WHERE user_id = ?)", (user_id,))
        conn.execute("DELETE FROM related WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM entities WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM chunks WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM summaries WHERE user_id = ?", (user_id,))


def delete_by_document(document_id: str, user_id: str = "") -> None:
    """Delete all graph nodes and mentions for a specific document."""
    if not document_id:
        return
    ensure_schema()
    with _db() as conn:
        conn.execute("DELETE FROM mentions WHERE chunk_id IN (SELECT chunk_id FROM chunks WHERE document_id = ?)", (document_id,))
        conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))

