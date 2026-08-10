"""POST /chat and GET /chat/stream — answer questions through the full retrieval pipeline."""
from __future__ import annotations

import json
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from ..config import settings
from ..core import generation, retrieval
from ..core.quota import (
    QuotaExceeded,
    check_docs_quota,
    get_plan,
    guest_trial_remaining,
    record_docs_questions,
    take_guest_question,
)
from ..core.clients import EmbeddingUnavailable
from ..errors import SearchUnavailable, internal_error
from ..schemas import ChatRequest, ChatResponse, Citation

router = APIRouter(tags=["chat"])


def _used_document_ids(candidates: list[dict]) -> list[str]:
    """Distinct document_ids actually retrieved for a question (for per-doc quotas)."""
    seen = set()
    out = []
    for c in candidates:
        doc_id = c.get("document_id")
        if doc_id and doc_id not in seen:
            seen.add(doc_id)
            out.append(doc_id)
    return out


def _enforce_pre_quota(user_id: str) -> None:
    """Cheap gate run *before* retrieval (guests' total question budget)."""
    if get_plan(user_id) == "trial":
        if guest_trial_remaining(user_id) <= 0:
            raise QuotaExceeded(
                "You've used all 3 free trial questions. Sign in for a free account "
                "with daily limits or upgrade to Pro for unlimited access."
            )


def _enforce_doc_quota(user_id: str, candidates: list[dict]) -> list[str]:
    """Check per-document daily caps for signed-in free users (pre-generation)."""
    doc_ids = _used_document_ids(candidates)
    check_docs_quota(user_id, doc_ids)
    return doc_ids


def _record_quota(user_id: str, doc_ids: list[str]) -> None:
    """Persist the consumed allowance.

    * trial guest: +1 question to the trial budget
    * free signed-in: +1 question per touched document
    * paid plans: no-op
    """
    plan = get_plan(user_id)
    if plan == "trial":
        try:
            take_guest_question(user_id)
        except QuotaExceeded:
            pass
    elif plan == "free":
        record_docs_questions(user_id, doc_ids)


def _citations(candidates: list[dict]) -> list[Citation]:
    out = []
    for c in candidates:
        cid = c.get("chunk_id")
        if cid:
            src = str(c.get("source") or "Document")
            raw_text = c.get("text")
            txt = (raw_text if isinstance(raw_text, str) else str(raw_text or ""))[:400]
            out.append(
                Citation(
                    chunk_id=str(cid),
                    source=src,
                    text=txt,
                    score=float(c.get("score", 0.0)),
                    via_graph=bool(c.get("via_graph", False)),
                )
            )
    return out


@router.post("/chat", response_model=ChatResponse)
async def chat(request: Request, req: ChatRequest) -> ChatResponse:
    if not req.question.strip():
        raise HTTPException(400, "Question must not be empty")

    auth_header = request.headers.get("Authorization", "")
    session_token = auth_header.replace("Bearer ", "").strip() if auth_header.startswith("Bearer ") else ""

    from ..core import user_db
    user_id = user_db.resolve_user_id(session_token)

    try:
        _enforce_pre_quota(user_id)
    except QuotaExceeded as exc:
        raise HTTPException(exc.code, exc.message) from exc

    from ..selfopt import hooks, scheduler
    scheduler.note_query()

    start = time.perf_counter()
    try:
        # Retrieval + generation are synchronous network I/O; offload off the event loop
        # so concurrent chats don't serialize behind each other. Canary scoping routes
        # a bucketed user to the challenger config for this one request only.
        with hooks.canary_scope(user_id):
            candidates, edges = await run_in_threadpool(
                retrieval.retrieve_with_trace,
                req.question,
                req.top_k,
                req.use_graph,
                user_id,
            )
            # Per-document daily caps are checked AFTER retrieval but BEFORE the (expensive)
            # LLM call so a limit breach never costs tokens.
            used_docs = _enforce_doc_quota(user_id, candidates)
            answer, run_id = await run_in_threadpool(
                generation.generate_answer_with_run_id, req.question, candidates
            )
            latency_ms = int((time.perf_counter() - start) * 1000)
            hooks.observe(who=user_id, latency_ms=latency_ms)
    except EmbeddingUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except SearchUnavailable:
        # Vector store could not be reached. This must surface as an explicit service
        # outage — users with documents cannot answer "I couldn't find context" to that.
        raise HTTPException(
            503,
            "Search is temporarily unavailable because the vector store could not be "
            "reached. Your uploads are safe — please retry in a moment.",
        ) from None
    except QuotaExceeded as exc:
        raise HTTPException(exc.code, exc.message) from exc
    except Exception as exc:
        raise internal_error(exc) from exc

    _record_quota(user_id, used_docs)

    # Deep-link this request's run when we captured its id; else fall back to the project.
    trace_url = None
    if settings.langchain_tracing_v2 and settings.langchain_api_key:
        base = f"https://smith.langchain.com/o/-/projects/p/{settings.langchain_project}"
        trace_url = f"{base}/r/{run_id}" if run_id else base

    return ChatResponse(
        answer=answer,
        citations=_citations(candidates),
        trace_url=trace_url,
        latency_ms=latency_ms,
        edges=[list(e) for e in edges],
    )


@router.get("/chat/stream")
def chat_stream(
    question: str,
    use_graph: bool = True,
    top_k: int = 0,
    user_token: str | None = None,
    conversation_id: str | None = None,
):
    """SSE endpoint — streams answer tokens, then a final citations+edges JSON event.

    Saves message to user conversation history if authenticated with user_token.
    """
    import time
    t0 = time.perf_counter()

    if not question.strip():
        raise HTTPException(400, "Question must not be empty")

    from ..core import user_db
    user_id = user_db.resolve_user_id(user_token)

    try:
        _enforce_pre_quota(user_id)
    except QuotaExceeded as exc:
        raise HTTPException(exc.code, exc.message) from exc

    def event_stream():
        full_answer = ""
        try:
            # Open the SSE channel first. The browser can immediately show that
            # it is working while retrieval runs instead of appearing frozen.
            yield f"data: {json.dumps({'status': 'Searching uploaded documents…'})}\n\n"
            candidates, edges = retrieval.retrieve_with_trace(
                question, top_k or None, use_graph, user_id
            )
            try:
                used_docs = _enforce_doc_quota(user_id, candidates)
            except QuotaExceeded as exc:
                yield f"data: {json.dumps({'error': exc.message, 'done': True})}\n\n"
                return
            citations = [c.model_dump() for c in _citations(candidates)]
            edge_lists = [list(e) for e in edges]
            for token in generation.stream_answer(question, candidates):
                full_answer += token
                yield f"data: {json.dumps({'token': token})}\n\n"
        except SearchUnavailable:
            yield f"data: {json.dumps({'error': 'Search is temporarily unavailable because the vector store could not be reached. Your uploads are safe — please retry in a moment.', 'done': True})}\n\n"
            return
        except Exception as exc:
            import logging
            logging.exception("Error during chat stream: %s", exc)
            err_msg = str(exc) or "Unable to generate an answer. Please retry."
            yield f"data: {json.dumps({'error': err_msg, 'done': True})}\n\n"
            return
        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        _record_quota(user_id, used_docs)

        # Save to chat history if authenticated
        saved_conv_id = conversation_id
        if user_token:
            from ..core import user_db
            usr = user_db.get_session_user(user_token)
            if usr:
                try:
                    res = user_db.save_chat_message(
                        user_id=usr["id"],
                        query=question,
                        answer=full_answer,
                        citations=citations,
                        edges=edge_lists,
                        conversation_id=conversation_id,
                    )
                    saved_conv_id = res["conversation_id"]
                except Exception:
                    pass

        yield f"data: {json.dumps({'citations': citations, 'edges': edge_lists, 'latency_ms': elapsed_ms, 'conversation_id': saved_conv_id, 'done': True})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/chat/conversations")
async def list_conversations(token: str):
    from ..core import user_db
    usr = user_db.get_session_user(token)
    if not usr:
        raise HTTPException(401, "Invalid or expired session token")
    return {"conversations": user_db.list_user_conversations(usr["id"])}


@router.get("/chat/conversations/{id}")
async def get_conversation(id: str, token: str):
    from ..core import user_db
    usr = user_db.get_session_user(token)
    if not usr:
        raise HTTPException(401, "Invalid or expired session token")
    conv = user_db.get_conversation_details(id, usr["id"])
    if not conv:
        raise HTTPException(404, "Conversation thread not found")
    return conv


@router.delete("/chat/conversations/{id}")
async def delete_conversation(id: str, token: str):
    from ..core import user_db
    usr = user_db.get_session_user(token)
    if not usr:
        raise HTTPException(401, "Invalid or expired session token")
    ok = user_db.delete_user_conversation(id, usr["id"])
    if not ok:
        raise HTTPException(404, "Conversation thread not found")
    return {"status": "ok"}
