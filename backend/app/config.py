"""Application configuration loaded from environment variables.

Everything downstream (vector store, graph, retrieval, eval) reads from the single
`settings` instance created at import time. See `.env.example` for the full list.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    # Cohere — the models actually in use for embeddings, chat, and rerank.
    cohere_api_key: str = ""
    cohere_embed_model: str = "embed-english-v3.0"
    cohere_chat_model: str = "command-a-03-2025"
    # embed-english-v3.0 returns 1024-dimensional vectors. Use 384 only with
    # embed-english-light-v3.0 — model and dimension must always match.
    cohere_embed_dim: int = 1024
    cohere_rerank_model: str = "rerank-english-v3.0"

    # Dense Embedding Provider ("cohere", "ollama", "nvidia")
    embedding_provider: str = "cohere"

    # Ollama Embeddings Config (supports host.docker.internal for Docker Desktop)
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_embed_model: str = "nomic-embed-text"
    ollama_embed_dim: int = 1024

    # NVIDIA NIM Embeddings Config
    nvidia_api_key: str = ""
    nvidia_endpoint: str = "https://integrate.api.nvidia.com/v1"
    nvidia_embed_model: str = "nvidia/nv-embedqa-e5-v5"
    nvidia_embed_dim: int = 1024

    # Supabase Authentication (Credentials loaded from backend .env)
    supabase_url: str = ""
    supabase_anon_key: str = ""
    next_public_supabase_url: str = ""
    next_public_supabase_anon_key: str = ""

    @property
    def get_supabase_url(self) -> str:
        import os
        from pathlib import Path
        val = (
            self.next_public_supabase_url
            or self.supabase_url
            or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
            or os.environ.get("SUPABASE_URL")
            or ""
        )
        if not val:
            for p in [Path("backend/.env"), Path(".env"), Path("../.env"), Path("d:/RAG Pipeline/backend/.env"), Path("d:/RAG Pipeline/.env")]:
                if p.exists():
                    try:
                        for line in p.read_text(encoding="utf-8").splitlines():
                            line = line.strip()
                            if line.startswith("NEXT_PUBLIC_SUPABASE_URL=") or line.startswith("SUPABASE_URL="):
                                val = line.split("=", 1)[1].strip().strip("'\"")
                                if val:
                                    break
                    except Exception:
                        pass
                if val:
                    break

        val = val.strip().strip("'\"")
        if val.endswith("/rest/v1/") or val.endswith("/rest/v1"):
            val = val.split("/rest/v1")[0]
        return val.strip().rstrip("/")

    @property
    def get_supabase_anon_key(self) -> str:
        import os
        from pathlib import Path
        val = (
            self.next_public_supabase_anon_key
            or self.supabase_anon_key
            or os.environ.get("NEXT_PUBLIC_SUPABASE_ANON_KEY")
            or os.environ.get("SUPABASE_ANON_KEY")
            or ""
        )
        if not val:
            for p in [Path("backend/.env"), Path(".env"), Path("../.env"), Path("d:/RAG Pipeline/backend/.env"), Path("d:/RAG Pipeline/.env")]:
                if p.exists():
                    try:
                        for line in p.read_text(encoding="utf-8").splitlines():
                            line = line.strip()
                            if line.startswith("NEXT_PUBLIC_SUPABASE_ANON_KEY=") or line.startswith("SUPABASE_ANON_KEY="):
                                val = line.split("=", 1)[1].strip().strip("'\"")
                                if val:
                                    break
                    except Exception:
                        pass
                if val:
                    break

        return val.strip().strip("'\"")





    # Pinecone
    pinecone_api_key: str = ""
    pinecone_index: str = "rag-pipeline-cohere"
    pinecone_cloud: str = "aws"
    pinecone_region: str = "us-east-1"

    # Stripe — subscription billing for paid plans. Empty keys disable checkout;
    # the webhook endpoint still works and 401s without a verifiable signature.
    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_pro_price_id: str = ""  # monthly Pro (e.g. price_1Q...)
    stripe_pro_yearly_price_id: str = ""  # yearly Pro (optional; falls back to monthly)
    stripe_success_url: str = "http://localhost:3000/dashboard?checkout=success"
    stripe_cancel_url: str = "http://localhost:3000/dashboard?checkout=canceled"

    # Groq — Ultra-fast LLM inference used for RAGAS judge and answer evaluation.
    groq_api_key: str = ""
    groq_llm_model: str = "llama-3.3-70b-versatile"

    # RAGAS judge pins — recorded alongside every eval run so scores stay comparable.
    ragas_judge_model: str = "llama-3.3-70b-versatile"
    ragas_timeout_s: float = 60.0

    # Neo4j
    neo4j_uri: str = "bolt://127.0.0.1:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "please-change-me"

    # LangSmith (langchain also reads these as env vars directly)
    langchain_tracing_v2: bool = True
    langchain_api_key: str = ""
    langchain_project: str = "neuro-adaptive-graphrag"
    langchain_endpoint: str = "https://api.smith.langchain.com"

    # App
    app_env: str = "development"  # "development" allows dev mode without enforcing secret keys
    api_key: str = ""  # required outside dev; compared with secrets.compare_digest
    admin_password: str = "Vedant6546"  # passcode required to unlock Admin Command Center
    # Signing secret for short-lived SSE tokens + answer_id bindings. Auto-derived from
    # api_key when unset so a single configured secret is enough for a normal deploy.
    signing_secret: str = ""
    sse_token_ttl_s: int = 60  # EventSource can't send headers → one-shot token instead
    answer_ttl_s: int = 3600  # how long an answer_id stays eligible for feedback
    backend_cors_origins: str = "http://localhost:3000,http://localhost:3001,http://127.0.0.1:3000,http://127.0.0.1:3001,*"
    # Chunking is now token-based (see ingestion._make_splitter): sizes are in tokens,
    # measured with tiktoken cl100k_base as a model-agnostic proxy (char fallback if
    # tiktoken can't load). 512/64 tokens is a solid retrieval default.
    chunk_size: int = 512
    chunk_overlap: int = 64
    # Small interactive candidate pools preserve quality after reranking while
    # avoiding unnecessary remote Pinecone/Cohere work.
    retrieve_top_k: int = 10
    rerank_top_n: int = 4
    rerank_min_score: float = 0.15  # drop passages below this Cohere relevance score
    expand_hops: int = 1
    graph_max_limit: int = 500  # hard cap on GET /graph limit (was unbounded)

    # Expansion blast-radius caps — a hub entity on a dense graph can otherwise fan out
    # into millions of paths before LIMIT applies.
    expand_max_paths: int = 250  # paths considered before aggregation
    expand_timeout_s: int = 10  # Neo4j transaction timeout for the expansion query
    embed_cache_size: int = 512  # LRU cache on query embeddings (repeat/eval traffic)

    # Retrieval fusion + abstention
    graph_fusion_beta: float = 0.05  # rerank_score + beta * log1p(path_weight)
    abstain_below_score: float = 0.30  # top rerank score under this ⇒ low-confidence answer

    # Bounds on interactive generation keep prompts and responses responsive.
    chat_max_tokens: int = 320
    chat_context_max_chars: int = 6000

    # Adaptive loop persistence + plasticity
    embedding_cache_path: str = ".data/graphsage_emb.pt"  # warm-start across eval runs
    graphsage_alpha: float = 0.6  # structural vs feedback blend weight
    graphsage_epochs: int = 15  # GraphSAGE training iterations
    edge_decay: float = 0.05  # fraction an untouched edge drifts toward neutral per half-life
    edge_decay_half_life_h: float = 168.0  # decay is time-based: decay ** (dt / half_life)
    retrain_min_events: int = 10  # GraphSAGE retrains after N reward events...
    retrain_min_interval_s: int = 900  # ...or this long since the last retrain, whichever first
    entity_match_threshold: float = 0.90  # cosine floor for embedding-based entity merge
    graph_confidence_threshold: float = 0.80  # LLM-reported confidence threshold for entities and relationships
    expansion_relevance_threshold: float = 0.35  # cosine floor between entities and user query to walk a path during graph expansion

    # Self-optimization subsystem control (selfopt never writes .env)
    selfopt_enabled: bool = True
    selfopt_tick_seconds: int = 300
    selfopt_canary_percent: int = 15
    selfopt_min_canary_queries: int = 40

    # Durable local state (SQLite; single file, WAL, survives restarts)
    state_db_path: str = ".data/state.db"
    # Legacy JSONL paths — still read once at startup to migrate into SQLite.
    eval_history_path: str = ".data/eval_runs.jsonl"
    feedback_path: str = ".data/feedback.jsonl"
    # Optional Redis for the rate limiter when running more than one process.
    redis_url: str = ""

    @property
    def is_dev(self) -> bool:
        return self.app_env.strip().lower() in {"dev", "development", "local", "test"}

    @property
    def secret(self) -> str:
        """Key used for HMAC signing. Falls back to api_key so one secret suffices."""
        return self.signing_secret or self.api_key

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.backend_cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
