from fastapi import APIRouter, Request
from neo4j.exceptions import Neo4jError, ServiceUnavailable
from starlette.concurrency import run_in_threadpool

from ..config import settings
from ..core import graphrag, user_db
from ..errors import internal_error

router = APIRouter(tags=["graph"])


def _is_neo4j_unavailable(exc: Exception) -> bool:
    if isinstance(exc, (ServiceUnavailable, Neo4jError)):
        return True
    msg = str(exc).lower()
    return "connection" in msg or "service unavailable" in msg or "neo4j" in msg


@router.get("/graph")
async def graph(request: Request, limit: int = 100, token: str | None = None) -> dict:
    limit = max(1, min(limit, settings.graph_max_limit))

    auth_header = request.headers.get("Authorization", "")
    session_token = token or (auth_header.replace("Bearer ", "").strip() if auth_header.startswith("Bearer ") else "")

    user_id = user_db.resolve_user_id(session_token)

    try:
        return await run_in_threadpool(graphrag.graph_snapshot, limit, user_id)
    except Exception as exc:
        if _is_neo4j_unavailable(exc):
            return {
                "nodes": [],
                "edges": [],
                "explanation": "The Knowledge Graph is unavailable because the Neo4j service is offline or misconfigured.",
            }
        raise internal_error(exc) from exc


@router.get("/graph/entity-details")
async def entity_details(name: str, request: Request, token: str | None = None) -> dict:
    auth_header = request.headers.get("Authorization", "")
    session_token = token or (auth_header.replace("Bearer ", "").strip() if auth_header.startswith("Bearer ") else "")
    user_id = user_db.resolve_user_id(session_token)

    try:
        return await run_in_threadpool(graphrag.get_entity_details, name, user_id)
    except Exception as exc:
        if _is_neo4j_unavailable(exc):
            return {
                "name": name,
                "type": "UNKNOWN",
                "rationale": "Graph service unavailable.",
                "relationships": [],
                "passages": [],
            }
        raise internal_error(exc) from exc


@router.get("/graph/summary")
async def graph_summary(request: Request, token: str | None = None) -> dict:
    auth_header = request.headers.get("Authorization", "")
    session_token = token or (auth_header.replace("Bearer ", "").strip() if auth_header.startswith("Bearer ") else "")
    user_id = user_db.resolve_user_id(session_token)

    try:
        return await run_in_threadpool(graphrag.get_graph_summary, user_id)
    except Exception as exc:
        if _is_neo4j_unavailable(exc):
            return {
                "total_entities": 0,
                "total_relationships": 0,
                "top_hubs": [],
                "entity_types": {},
                "rules": [
                    "Knowledge Graph is unavailable because Neo4j is offline.",
                ],
                "summary": "The Knowledge Graph service is currently unavailable. Please start Neo4j to restore graph summaries and relationships.",
            }
        raise internal_error(exc) from exc


@router.post("/graph/clear")
async def clear_graph(request: Request, token: str | None = None) -> dict:
    user_id = _user_id(request, token)
    try:
        from ..core import vectorstore
        await run_in_threadpool(graphrag.clear_user_graph, user_id)
        await run_in_threadpool(vectorstore.clear_user_vectors, user_id)
        return {"status": "success", "message": "Knowledge Graph and vector store cleared successfully."}
    except Exception as exc:
        raise internal_error(exc) from exc


def _user_id(request: Request, token: str | None) -> str:
    auth_header = request.headers.get("Authorization", "")
    session_token = token or (auth_header.replace("Bearer ", "").strip() if auth_header.startswith("Bearer ") else "")
    return user_db.resolve_user_id(session_token)



