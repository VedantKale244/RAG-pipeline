"""Lazily-constructed singleton clients for the external services.

Every client is created on first access and cached, so importing this module is cheap
and tests can monkeypatch the factory functions.
"""
from __future__ import annotations

import logging
import time
from functools import lru_cache

import cohere
from langchain_cohere import ChatCohere, CohereEmbeddings
from neo4j import Driver, GraphDatabase
from pinecone import Pinecone, ServerlessSpec

from ..config import settings

logger = logging.getLogger("app")


from .embedding_provider import EmbeddingProvider, EmbeddingUnavailable, get_embedding_provider


@lru_cache
def embeddings() -> EmbeddingProvider:
    """Return the active provider-agnostic EmbeddingProvider (defaults to Cohere)."""
    return get_embedding_provider()


@lru_cache
def _cohere_llm() -> ChatCohere:
    return ChatCohere(
        model=settings.cohere_chat_model,
        cohere_api_key=settings.cohere_api_key,
        temperature=0.1,
        max_tokens=settings.chat_max_tokens,
    )


@lru_cache
def chat_llm():
    """Primary chat model: Groq when a key is set, with an automatic fallback to
    Cohere whenever a Groq call fails (rate limit / daily-token quota included).
    Without a Groq key, it always uses Cohere."""
    if settings.groq_api_key:
        try:
            from langchain_groq import ChatGroq

            groq_llm = ChatGroq(
                model=settings.groq_llm_model or "llama-3.3-70b-versatile",
                groq_api_key=settings.groq_api_key,
                temperature=0.1,
                max_tokens=settings.chat_max_tokens,
            )
            try:
                return groq_llm.with_fallbacks(
                    [_cohere_llm()],
                    exceptions_to_handle=(Exception,),
                )
            except Exception as exc:
                logger.warning("ChatGroq fallback wiring failed: %s", exc)
                return groq_llm
        except Exception as exc:
            logger.warning("ChatGroq init failed: %s", exc)

    return _cohere_llm()


@lru_cache
def cohere_client() -> cohere.Client:
    return cohere.Client(api_key=settings.cohere_api_key)


def safe_embed_query(text: str) -> list[float]:
    """Safely embed a single query string using the active EmbeddingProvider."""
    return get_embedding_provider().embed_query(text)


def safe_embed_documents(texts: list[str]) -> list[list[float]]:
    """Safely embed documents 1:1 using the active EmbeddingProvider."""
    return get_embedding_provider().embed_documents(texts)



def _index_names(pc: Pinecone) -> set[str]:
    try:
        indexes = pc.list_indexes() or []
    except Exception:
        return set()
    names: set[str] = set()
    for item in indexes:
        if isinstance(item, str):
            names.add(item)
        elif isinstance(item, dict):
            name = item.get("name")
            if name:
                names.add(str(name))
        elif hasattr(item, "name"):
            names.add(str(item.name))
    return names


def _index_dimension(pc: Pinecone, index_name: str) -> int | None:
    try:
        desc = pc.describe_index(index_name)
        if isinstance(desc, dict):
            dim = desc.get("dimension")
        else:
            dim = getattr(desc, "dimension", None)
        return int(dim) if dim is not None else None
    except Exception:
        return None


@lru_cache
def pinecone_index():
    """Return the Pinecone index handle, creating the index if needed."""
    pc = Pinecone(api_key=settings.pinecone_api_key)
    index_name = settings.pinecone_index

    if index_name not in _index_names(pc):
        pc.create_index(
            name=index_name,
            dimension=settings.cohere_embed_dim,
            metric="cosine",
            spec=ServerlessSpec(
                cloud=settings.pinecone_cloud,
                region=settings.pinecone_region,
            ),
        )

    dim = _index_dimension(pc, index_name)
    if dim is not None and dim != settings.cohere_embed_dim:
        raise RuntimeError(
            f"Pinecone index '{index_name}' uses dimension {dim} but "
            f"COHERE_EMBED_DIM is {settings.cohere_embed_dim}. "
            "Set COHERE_EMBED_DIM to match the index, or recreate the index "
            "after changing the embedding model."
        )

    return pc.Index(index_name)


@lru_cache
def neo4j_driver() -> Driver:
    return GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
        max_connection_lifetime=1800,
        max_connection_pool_size=50,
        connection_timeout=15.0,
    )


def close_clients() -> None:
    """Called from the FastAPI lifespan shutdown hook."""
    try:
        neo4j_driver().close()
    except Exception:
        pass
