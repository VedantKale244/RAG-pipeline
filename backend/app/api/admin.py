"""GET /admin/stats & DELETE /admin/documents/{doc_id} — admin dashboard endpoints."""
from __future__ import annotations

import json
import secrets
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from ..config import settings
from ..core import fallback_graph, graphrag, user_db, vectorstore
from ..core.clients import neo4j_driver
from ..errors import internal_error
router = APIRouter(tags=["admin"])


class AdminVerifyRequest(BaseModel):
    password: str


import time

_LOGIN_ATTEMPTS: dict[str, dict] = {}


def _get_client_ip(request: Request) -> str:
    return request.headers.get("x-forwarded-for") or (request.client.host if request.client else "127.0.0.1")


def _check_ip_lockout(client_ip: str) -> None:
    now = time.time()
    record = _LOGIN_ATTEMPTS.get(client_ip)
    if record and record.get("attempts", 0) >= 5:
        elapsed = now - record.get("last_failed", 0)
        if elapsed < 60:
            remaining = int(60 - elapsed)
            raise HTTPException(
                429,
                f"Too many failed login attempts. Admin Portal locked for {remaining}s."
            )
        else:
            _LOGIN_ATTEMPTS.pop(client_ip, None)


def _record_failed_attempt(client_ip: str) -> int:
    now = time.time()
    record = _LOGIN_ATTEMPTS.get(client_ip, {"attempts": 0, "last_failed": 0})
    record["attempts"] += 1
    record["last_failed"] = now
    _LOGIN_ATTEMPTS[client_ip] = record
    return record["attempts"]


def _reset_attempts(client_ip: str) -> None:
    _LOGIN_ATTEMPTS.pop(client_ip, None)


def _check_admin_pass(provided: str | None) -> bool:
    if not provided or not isinstance(provided, str):
        return False
    target = (settings.admin_password or "Vedant6546").strip()
    return secrets.compare_digest(provided.strip(), target)


async def verify_admin_access(request: Request) -> None:
    provided = (
        request.headers.get("x-admin-password")
        or request.headers.get("x-api-key")
        or request.query_params.get("api_key")
        or request.query_params.get("admin_password")
    )
    if not _check_admin_pass(provided):
        raise HTTPException(401, "Invalid or missing Admin Passcode")


@router.post("/admin/verify")
async def verify_admin(request: Request, req: AdminVerifyRequest) -> dict:
    client_ip = _get_client_ip(request)
    _check_ip_lockout(client_ip)

    if _check_admin_pass(req.password):
        _reset_attempts(client_ip)
        return {"status": "authenticated", "valid": True}

    attempts = _record_failed_attempt(client_ip)
    remaining = max(0, 5 - attempts)
    if attempts >= 5:
        raise HTTPException(
            429,
            "Too many failed login attempts. Admin Portal locked for 60 seconds."
        )
    raise HTTPException(
        401,
        f"Invalid Admin Passcode. {remaining} attempt(s) remaining before 60s lockout."
    )


def _get_admin_stats() -> dict:
    docs = []
    total_chunks = 0
    total_nodes = 0
    total_edges = 0

    try:
        with neo4j_driver().session() as session:
            # Get documents and chunk counts
            res = session.run(
                "MATCH (c:Chunk) "
                "RETURN coalesce(c.source, 'Unknown') AS source, "
                "       c.document_id AS document_id, "
                "       count(c) AS chunk_count"
            )
            for record in res:
                docs.append({
                    "source": record["source"],
                    "document_id": record["document_id"],
                    "chunk_count": record["chunk_count"],
                })
                total_chunks += record["chunk_count"]

            # Get entity & relationship totals
            n_res = session.run("MATCH (e:Entity) RETURN count(e) AS cnt").single()
            total_nodes = n_res["cnt"] if n_res else 0

            r_res = session.run("MATCH ()-[r:RELATED]->() RETURN count(r) AS cnt").single()
            total_edges = r_res["cnt"] if r_res else 0
    except Exception:
        # Fallback gracefully if Neo4j is unreachable or empty
        pass

    # Secondary fallback to SQLite graph if Neo4j returned 0 documents
    if not docs:
        try:
            fg = fallback_graph.admin_documents()
            for d in fg.get("documents", []):
                docs.append({
                    "source": d.get("source") or d.get("filename") or "Unknown",
                    "document_id": d.get("document_id", ""),
                    "chunk_count": d.get("chunk_count", 0),
                })
                total_chunks += d.get("chunk_count", 0)
            total_nodes = fg.get("total_entities", 0)
            total_edges = fg.get("total_relationships", 0)
        except Exception:
            pass

    # Tertiary fallback to user_documents table
    if not docs:
        try:
            with user_db._get_db() as conn:
                rows = conn.execute("SELECT filename AS source, document_id FROM user_documents ORDER BY uploaded_at DESC").fetchall()
                for r in rows:
                    docs.append({
                        "source": r["source"],
                        "document_id": r["document_id"],
                        "chunk_count": 1,
                    })
                    total_chunks += 1
        except Exception:
            pass

    return {
        "documents": docs,
        "total_documents": len(docs),
        "total_chunks": total_chunks,
        "total_nodes": total_nodes,
        "total_edges": total_edges,
        "users": user_db.user_stats(),
        "config": {
            "llm": settings.cohere_chat_model,
            "embeddings": settings.cohere_embed_model,
            "embed_dim": settings.cohere_embed_dim,
            "vector_store": "Pinecone Serverless (" + settings.pinecone_index + ")",
            "reranker": settings.cohere_rerank_model,
            "top_k": settings.retrieve_top_k,
            "graph_fanout": settings.expand_hops,
            "rerank_floor": settings.rerank_min_score,
        }
    }



@router.get("/admin/users")
async def admin_users(request: Request) -> dict:
    await verify_admin_access(request)
    try:
        users = await run_in_threadpool(user_db.list_users)
        graph_stats = await run_in_threadpool(fallback_graph.admin_users_graph_stats)
        for u in users:
            g = graph_stats.get(u["id"]) or {}
            u["document_count"] = g.get("document_count", 0)
            u["chunk_count"] = g.get("chunk_count", 0)
            u["entity_count"] = g.get("entity_count", 0)
        return {
            "users": users,
            "stats": await run_in_threadpool(user_db.user_stats),
        }
    except Exception as exc:
        raise internal_error(exc) from exc


def _ingest_jobs_report() -> list[dict]:
    """Upload/ingestion job history from ``data/ingest_jobs.db``."""
    db_path = Path(__file__).resolve().parent.parent.parent / "data" / "ingest_jobs.db"
    try:
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        with conn:
            rows = conn.execute(
                "SELECT job_id, status, filename, progress, result, error FROM ingest_jobs "
                "ORDER BY rowid DESC LIMIT 200"
            ).fetchall()
    except Exception:
        return []
    jobs = []
    for r in rows:
        rec = dict(r)
        rec["chunks"] = rec["entities"] = rec["relationships"] = rec["document_id"] = None
        result = rec.pop("result")
        if result:
            try:
                parsed = json.loads(result)
                rec["chunks"] = parsed.get("chunks")
                rec["entities"] = parsed.get("entities")
                rec["relationships"] = parsed.get("relationships")
                rec["document_id"] = parsed.get("document_id")
            except Exception:
                pass
        jobs.append(rec)
    return jobs


def _users_email_map() -> dict[str, str]:
    try:
        return {u["id"]: u["email"] for u in user_db.list_users()}
    except Exception:
        return {}


@router.get("/admin/documents")
async def admin_documents(request: Request) -> dict:
    await verify_admin_access(request)
    try:
        payload = await run_in_threadpool(fallback_graph.admin_documents)
        email_map = _users_email_map()
        for d in payload["documents"]:
            uid = d.get("user_id")
            d["user_email"] = email_map.get(uid) or uid or "unknown"
        payload["ingest_jobs"] = await run_in_threadpool(_ingest_jobs_report)
        return payload
    except Exception as exc:
        raise internal_error(exc) from exc


@router.get("/admin/stats")
async def admin_stats(request: Request) -> dict:
    await verify_admin_access(request)
    try:
        return await run_in_threadpool(_get_admin_stats)
    except Exception as exc:
        raise internal_error(exc) from exc


@router.delete("/admin/documents/{document_id}")
async def delete_document(request: Request, document_id: str) -> dict:
    await verify_admin_access(request)
    try:
        vec_deleted = await run_in_threadpool(vectorstore.delete_by_document, document_id)
        graph_stats = await run_in_threadpool(graphrag.delete_by_document, document_id)
        return {
            "status": "deleted",
            "document_id": document_id,
            "vectors_deleted": vec_deleted,
            "graph_stats": graph_stats,
        }
    except Exception as exc:
        raise internal_error(exc) from exc

