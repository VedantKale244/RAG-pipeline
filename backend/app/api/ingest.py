"""POST /ingest — upload a document into the vector store + knowledge graph.

Ingestion is asynchronous: the upload is validated and spooled to a temp file, a job is
registered, and the request returns a ``job_id`` immediately. The pipeline (chunk →
embed → extract → graph write) runs in a background task; poll
``GET /ingest/status/{job_id}`` for progress and the final stats.

Job rows are persisted in SQLite (``data/ingest_jobs.db``), not just memory, so a
backend reload — or a worker restart — never silently drops a job the frontend is
polling. Completed/failed rows are rehydrated into the in-memory table on import.
"""
import sqlite3
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Request, UploadFile

from ..core import ingestion
from ..ratelimit import limiter
from ..schemas import IngestJobResponse, IngestStatusResponse

router = APIRouter(tags=["ingest"])

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MiB
_CHUNK = 1024 * 1024  # stream in 1 MiB chunks

# Job table: memory-backed for fast lookups, mirrored to SQLite so status survives
# reloads/restarts. Single process is fine for dev; move to Redis for multi-instance.
_JOBS: dict[str, dict] = {}
_MAX_JOBS = 200  # drop oldest finished jobs past this to bound memory

_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "ingest_jobs.db"


def _job_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _init_job_db() -> None:
    with _job_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ingest_jobs (
                job_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                filename TEXT NOT NULL DEFAULT '',
                progress TEXT,
                result TEXT,
                error TEXT
            )
            """
        )
        # Rehydrate persisted jobs that finished before this process started so the
        # frontend polling a pre-restart job_id still gets a terminal status.
        try:
            with _job_db() as conn:
                for row in conn.execute(
                    "SELECT job_id, status, filename, progress, result, error FROM ingest_jobs"
                ):
                    rec = dict(row)
                    if rec["result"]:
                        import json

                        rec["result"] = json.loads(rec["result"])
                    if rec["job_id"] not in _JOBS:
                        _JOBS[rec["job_id"]] = rec
        except Exception:
            pass


def _persist_job(job_id: str) -> None:
    """Write a job row to SQLite (runs right after each in-memory mutation)."""
    rec = _JOBS.get(job_id)
    if rec is None:
        return
    import json

    try:
        with _job_db() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO ingest_jobs (job_id, status, filename, progress, result, error)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    rec.get("status", ""),
                    rec.get("filename", ""),
                    rec.get("progress"),
                    json.dumps(rec["result"]) if rec.get("result") else None,
                    rec.get("error"),
                ),
            )
    except Exception:
        pass


_init_job_db()


def _run_job(job_id: str, tmp_path: Path, filename: str, user_id: str = "guest", clear_previous: bool = False) -> None:
    """Background worker: runs the full ingest pipeline, records outcome in the job table.

    Uploads are committed straight to the vector store and knowledge graph — there is no
    pending/approval staging step.

    ``clear_previous`` replaces *only this document* (same user+filename → same
    document_id), never the whole user's index. That keeps multiple uploaded files
    live instead of wiping the previous one.
    """
    _JOBS[job_id]["status"] = "running"
    _JOBS[job_id]["progress"] = "Starting document ingestion..."
    _persist_job(job_id)

    if clear_previous and user_id:
        try:
            from ..core import graphrag, vectorstore
            _JOBS[job_id]["progress"] = f"Clearing previous document graph and vectors for '{filename}'..."
            _persist_job(job_id)
            vectorstore.clear_user_vectors(user_id)
            graphrag.clear_user_graph(user_id)
        except Exception as exc:
            logger.warning("Error clearing previous graph/vectors: %s", exc)


    def _on_progress(msg: str):
        _JOBS[job_id]["progress"] = msg
        _persist_job(job_id)

    try:
        stats = ingestion.ingest_file(tmp_path, filename=filename, user_id=user_id, progress_callback=_on_progress)
        # Charge the free-plan daily upload allowance only after a successful commit.
        # Re-upload of the same filename maps to the same document_id, so a deduped
        # "already up-to-date" re-upload won't consume a second slot.
        from ..core.quota import record_upload
        doc_id = ingestion.document_id_for(user_id, filename)
        record_upload(user_id, doc_id)
        from ..core import user_db
        user_db.record_user_document(user_id, filename, doc_id)
        _JOBS[job_id].update(status="done", progress="Ingestion completed", result=stats)
        _persist_job(job_id)
    except Exception as exc:
        # No internals leak — the job table is behind auth, but keep it terse anyway.
        _JOBS[job_id].update(status="failed", progress="Failed", error=str(exc)[:200])
        _persist_job(job_id)
    finally:
        tmp_path.unlink(missing_ok=True)
    # Bound the table: evict oldest finished jobs past this to bound memory.
    if len(_JOBS) > _MAX_JOBS:
        for jid in list(_JOBS):
            if _JOBS[jid]["status"] in {"done", "failed"} and len(_JOBS) > _MAX_JOBS:
                _JOBS.pop(jid, None)


@router.get("/ingest/check-duplicate")
async def check_duplicate(filename: str, request: Request) -> dict:
    """Check if a logged-in user has already uploaded a document with the given filename."""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip() if auth_header.startswith("Bearer ") else ""
    if not token:
        token = request.query_params.get("user_token", "")

    from ..core import user_db
    user_id = user_db.resolve_user_id(token)
    exists = user_db.has_user_document(user_id, filename)
    return {"exists": exists, "filename": filename, "user_id": user_id}


@router.get("/ingest/user-documents")
async def get_user_documents(request: Request) -> dict:
    """Retrieve list of uploaded documents for the current user."""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip() if auth_header.startswith("Bearer ") else ""
    if not token:
        token = request.query_params.get("user_token", "")

    from ..core import user_db
    user_id = user_db.resolve_user_id(token)
    docs = user_db.get_user_documents(user_id)
    return {"documents": docs, "total": len(docs)}



@router.post("/ingest", response_model=IngestJobResponse, status_code=202)
@limiter.limit("20/minute")  # ponytail: upload + per-chunk LLM extraction — expensive, throttle it
async def ingest(
    request: Request,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    clear_previous: bool = False,
) -> IngestJobResponse:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".txt", ".md", ".pdf", ".docx"}:
        raise HTTPException(400, f"Unsupported file type: {suffix or 'unknown'}")

    # Fast-reject on the declared size, but still enforce the real cap while
    # streaming — Content-Length is client-supplied and spoofable.
    if file.size is not None and file.size > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large (max 25 MiB)")

    user_token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    if not user_token:
        user_token = request.query_params.get("user_token", "")
    
    from ..core import user_db
    user_id = user_db.resolve_user_id(user_token)

    # Free signed-in accounts get a strict daily upload cap; guests & paid plans don't.
    from ..core.quota import can_upload_day
    if not can_upload_day(user_id):
        raise HTTPException(
            429,
            "Daily upload limit reached (3 documents per day on the free plan). "
            "Upgrade to Pro for unlimited uploads.",
        )

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = Path(tmp.name)
        written = 0
        while chunk := await file.read(_CHUNK):
            written += len(chunk)
            if written > MAX_UPLOAD_BYTES:
                tmp.close()
                tmp_path.unlink(missing_ok=True)
                raise HTTPException(413, "File too large (max 25 MiB)")
            tmp.write(chunk)

    job_id = uuid.uuid4().hex[:12]
    filename = file.filename or tmp_path.name
    _JOBS[job_id] = {"status": "queued", "filename": filename, "user_id": user_id}
    _persist_job(job_id)
    background.add_task(_run_job, job_id, tmp_path, filename, user_id, clear_previous)
    return IngestJobResponse(job_id=job_id, status="queued", filename=filename)


@router.get("/ingest/status/{job_id}", response_model=IngestStatusResponse)
async def ingest_status(job_id: str) -> IngestStatusResponse:
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job id")
    return IngestStatusResponse(
        job_id=job_id,
        status=job["status"],
        filename=job.get("filename", ""),
        progress=job.get("progress"),
        result=job.get("result"),
        error=job.get("error"),
    )


@router.post("/guest/cleanup")
async def guest_cleanup(request: Request) -> dict:
    """Purge temporary vector embeddings and graph nodes for a guest session."""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip() if auth_header.startswith("Bearer ") else ""
    if not token:
        token = request.query_params.get("user_token", "")

    if not token or not token.startswith("guest"):
        return {"status": "skipped", "reason": "Not a guest token"}

    user_id = token
    from ..core import vectorstore, graphrag, user_db
    from starlette.concurrency import run_in_threadpool

    vec_del = await run_in_threadpool(vectorstore.delete_by_user, user_id)
    graph_stats = await run_in_threadpool(graphrag.delete_by_user, user_id)
    user_db.delete_guest_messages(user_id)

    return {
        "status": "cleaned",
        "user_id": user_id,
        "vectors_deleted": vec_del,
        "graph_stats": graph_stats,
    }


