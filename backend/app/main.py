"""FastAPI application entrypoint.

Wires observability, ensures the graph schema exists, mounts the API routers, and enables
CORS for the Next.js frontend. Run with ``uvicorn app.main:app``.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from .api import account, admin, auth, billing, chat, eval as eval_api, feedback, graph, ingest, selfopt_api, supabase_auth
from .config import settings
from .core.clients import close_clients
from .observability import init_observability
from .ratelimit import limiter
from .security import verify_api_key
from .selfopt import scheduler

@asynccontextmanager
async def lifespan(app: FastAPI):
    tracing = init_observability()
    app.state.tracing = tracing

    # Ensure Neo4j constraints exist up front and purge legacy un-scoped guest data.
    try:
        from .core import graphrag, vectorstore

        graphrag.ensure_schema()
        graphrag.purge_legacy_guest_data()
        vectorstore.purge_legacy_guest_data()
    except Exception:
        # Neo4j/Pinecone may not be up yet in dev; ingestion will retry ensure_schema().
        pass

    from .selfopt import init as selfopt_init

    selfopt_init()
    task = scheduler.start(asyncio.get_event_loop())
    app.state.selfopt_task = task
    yield
    if task is not None:
        task.cancel()
    close_clients()


app = FastAPI(
    title="Neuro-Adaptive GraphRAG Pipeline",
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

from .selfopt.errors import CaptureMiddleware
app.add_middleware(CaptureMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
    ],
    allow_origin_regex=r"https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_auth = [Depends(verify_api_key)]
app.include_router(auth.router)
app.include_router(supabase_auth.router)
app.include_router(ingest.router, dependencies=_auth)
app.include_router(chat.router, dependencies=_auth)
app.include_router(eval_api.router, dependencies=_auth)
app.include_router(graph.router, dependencies=_auth)
app.include_router(feedback.router, dependencies=_auth)
app.include_router(admin.router, dependencies=_auth)
app.include_router(selfopt_api.router, dependencies=_auth)
app.include_router(account.router, dependencies=_auth)
app.include_router(billing.router, dependencies=_auth)
app.include_router(billing.webhook_router)  # public: Stripe-signed webhooks


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "tracing": getattr(app.state, "tracing", False),
        "llm": settings.cohere_chat_model,
        "embeddings": settings.cohere_embed_model,
        "embed_dim": settings.cohere_embed_dim,
        "vector_store": "pinecone",
        "reranker": settings.cohere_rerank_model,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_dirs=["app"],
        timeout_keep_alive=65,
    )
