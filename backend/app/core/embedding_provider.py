"""Provider-agnostic Dense Embedding Layer Interface & Implementations.

Class Hierarchy:
    EmbeddingProvider (ABC)
       ├── LocalEmbedding (Ollama / Local HTTP endpoint)
       ├── NvidiaEmbedding (NVIDIA NIM API)
       └── CohereEmbedding (Cohere API - Default)

Enforces fail-fast dimension validation against target index requirements.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod

from ..config import settings

logger = logging.getLogger("app")


class EmbeddingUnavailable(RuntimeError):
    """Raised when dense embeddings cannot be produced by the active provider."""


class DimensionMismatchError(RuntimeError):
    """Raised when the provider output dimension does not match the target index dimension."""


class EmbeddingProvider(ABC):
    """Abstract Base Class for dense vector embedding providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """String identifier of the active provider."""
        pass

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Expected output vector dimension."""
        pass

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """Embed a single query string into a dense vector."""
        pass

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of document strings into dense vectors 1:1."""
        pass

    def validate_dimension(self, expected_dim: int) -> None:
        """Fail-fast validation comparing provider output dimension with index requirement."""
        if self.dimension != expected_dim:
            raise DimensionMismatchError(
                f"EmbeddingProvider '{self.provider_name}' produces {self.dimension}-dim vectors, "
                f"but target index requires {expected_dim}-dim vectors. "
                "Reconfigure provider dimension or recreate vector index."
            )


class LocalEmbedding(EmbeddingProvider):
    """Local dense embedding provider (Ollama / Local HTTP endpoint, supporting Docker Desktop)."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        dim: int | None = None,
    ):
        self._base_url = (base_url or settings.ollama_base_url or "http://127.0.0.1:11434").rstrip("/")
        self._model = model or settings.ollama_embed_model
        self._dim = dim or settings.ollama_embed_dim

    @property
    def provider_name(self) -> str:
        return "local"

    @property
    def dimension(self) -> int:
        return self._dim

    def _post_api(self, endpoint: str, payload: dict) -> dict:
        url = f"{self._base_url}/api/{endpoint}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="ignore")
            raise EmbeddingUnavailable(
                f"Local embedding server returned HTTP {exc.code} for endpoint '{endpoint}': {err_body}"
            ) from exc
        except urllib.error.URLError as exc:
            raise EmbeddingUnavailable(
                f"Local embedding connection failed at '{url}'. Ensure Ollama or local server is running and OLLAMA_BASE_URL is reachable: {exc}"
            ) from exc
        except Exception as exc:
            raise EmbeddingUnavailable(f"Local embedding request failed: {exc}") from exc

    def embed_query(self, text: str) -> list[float]:
        clean = (text or "").strip()
        if not clean:
            raise EmbeddingUnavailable("Cannot embed an empty query.")
        
        # Try primary batch/query endpoint /api/embed
        try:
            payload = {"model": self._model, "input": clean}
            resp = self._post_api("embed", payload)
            embeddings = resp.get("embeddings") or []
            if embeddings and len(embeddings[0]) > 0:
                vec = embeddings[0]
                if len(vec) != self.dimension:
                    self.validate_dimension(len(vec))
                return vec
        except Exception as exc:
            logger.debug("Ollama /api/embed query call failed, trying legacy /api/embeddings: %s", exc)

        # Fallback to legacy endpoint /api/embeddings
        payload = {"model": self._model, "prompt": clean}
        resp = self._post_api("embeddings", payload)
        vec = resp.get("embedding") or []
        if not vec:
            raise EmbeddingUnavailable(f"Local provider returned empty embedding for model '{self._model}'.")
        if len(vec) != self.dimension:
            self.validate_dimension(len(vec))
        return vec

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        clean_docs = [(t or "").strip() or "passage" for t in texts]
        if not clean_docs:
            return []

        # Try native batch embedding via /api/embed in chunks of 16
        all_vectors: list[list[float]] = []
        batch_size = 16
        try:
            for i in range(0, len(clean_docs), batch_size):
                batch = clean_docs[i : i + batch_size]
                payload = {"model": self._model, "input": batch}
                resp = self._post_api("embed", payload)
                batch_vectors = resp.get("embeddings") or []
                if len(batch_vectors) != len(batch):
                    raise ValueError(f"Expected {len(batch)} embeddings, got {len(batch_vectors)}")
                all_vectors.extend(batch_vectors)

            if all_vectors and len(all_vectors[0]) != self.dimension:
                self.validate_dimension(len(all_vectors[0]))
            return all_vectors

        except Exception as exc:
            logger.warning("Ollama batch /api/embed document call failed, falling back to 1-by-1 queries: %s", exc)
            return [self.embed_query(doc) for doc in clean_docs]



class NvidiaEmbedding(EmbeddingProvider):
    """NVIDIA NIM API embedding provider (configurable model, endpoint, API key, and dimension)."""

    def __init__(
        self,
        api_key: str | None = None,
        endpoint: str | None = None,
        model: str | None = None,
        dim: int | None = None,
    ):
        self._api_key = settings.nvidia_api_key if api_key is None else api_key
        self._endpoint = ((settings.nvidia_endpoint if endpoint is None else endpoint) or "https://integrate.api.nvidia.com/v1").rstrip("/")
        self._model = settings.nvidia_embed_model if model is None else model
        self._dim = settings.nvidia_embed_dim if dim is None else dim

    @property
    def provider_name(self) -> str:
        return "nvidia"

    @property
    def dimension(self) -> int:
        return self._dim

    def _post_api(self, payload: dict) -> dict:
        if not self._api_key:
            raise EmbeddingUnavailable(
                "NVIDIA API key missing. Set NVIDIA_API_KEY environment variable or settings."
            )
        url = f"{self._endpoint}/embeddings"
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="ignore")
            raise EmbeddingUnavailable(f"NVIDIA NIM API HTTP {exc.code} error: {err_body}") from exc
        except urllib.error.URLError as exc:
            raise EmbeddingUnavailable(f"NVIDIA NIM API connection error at '{url}': {exc}") from exc
        except Exception as exc:
            raise EmbeddingUnavailable(f"NVIDIA NIM embedding call failed: {exc}") from exc

    def embed_query(self, text: str) -> list[float]:
        clean = (text or "").strip()
        if not clean:
            raise EmbeddingUnavailable("Cannot embed an empty query.")
        payload = {"input": [clean], "model": self._model, "input_type": "query"}
        resp = self._post_api(payload)
        data = resp.get("data") or []
        if not data or not data[0].get("embedding"):
            raise EmbeddingUnavailable("NVIDIA NIM API returned empty embedding payload.")
        vec = data[0]["embedding"]
        if len(vec) != self.dimension:
            self.validate_dimension(len(vec))
        return vec

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        clean_docs = [(t or "").strip() or "empty passage" for t in texts]
        if not clean_docs:
            return []
        payload = {"input": clean_docs, "model": self._model, "input_type": "passage"}
        resp = self._post_api(payload)
        data = resp.get("data") or []
        if len(data) != len(clean_docs):
            return [self.embed_query(doc) for doc in clean_docs]
        vectors = [item.get("embedding", []) for item in data]
        if vectors and len(vectors[0]) != self.dimension:
            self.validate_dimension(len(vectors[0]))
        return vectors


class CohereEmbedding(EmbeddingProvider):
    """Cohere dense embedding provider (default)."""

    def __init__(self, model: str | None = None, api_key: str | None = None, dim: int | None = None):
        self._model = model or settings.cohere_embed_model
        self._api_key = api_key or settings.cohere_api_key
        self._dim = dim or settings.cohere_embed_dim
        self._cached_client = None

    @property
    def provider_name(self) -> str:
        return "cohere"

    @property
    def dimension(self) -> int:
        return self._dim

    def _get_langchain_embeddings(self):
        if self._cached_client is None:
            from langchain_cohere import CohereEmbeddings
            self._cached_client = CohereEmbeddings(
                model=self._model,
                cohere_api_key=self._api_key,
                max_retries=1,
            )
        return self._cached_client

    def _retry_embed(self, fn, *args):
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                return fn(*args)
            except Exception as exc:
                last_exc = exc
                msg = str(exc).lower()
                if "month" in msg or "quota" in msg or "billing" in msg:
                    raise EmbeddingUnavailable(
                        "Cohere API quota exhausted - embeddings unavailable. "
                        "Replace COHERE_API_KEY with a key that has active quota."
                    ) from exc
                if ("429" in msg or "rate limit" in msg or "too many requests" in msg) and attempt < 2:
                    time.sleep(2.0 * (attempt + 1))
                    continue
                break
        raise EmbeddingUnavailable(f"Cohere embedding call failed: {last_exc}") from last_exc

    def embed_query(self, text: str) -> list[float]:
        clean = (text or "").strip()
        if not clean:
            raise EmbeddingUnavailable("Cannot embed an empty query.")
        res = self._retry_embed(self._get_langchain_embeddings().embed_query, clean)
        if len(res) != self.dimension:
            self.validate_dimension(len(res))
        return res

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        clean_docs = [(t or "").strip() or "empty passage" for t in texts]
        if not clean_docs:
            return []
        res = self._retry_embed(self._get_langchain_embeddings().embed_documents, clean_docs)
        if res and len(res[0]) != self.dimension:
            self.validate_dimension(len(res[0]))
        return res


# Backward compatibility aliases
OllamaEmbeddingProvider = LocalEmbedding
NvidiaEmbeddingProvider = NvidiaEmbedding
CohereEmbeddingProvider = CohereEmbedding


def get_embedding_provider(name: str | None = None) -> EmbeddingProvider:
    """Factory creating and validating the configured EmbeddingProvider instance."""
    provider_type = (name or settings.embedding_provider or "cohere").strip().lower()

    if provider_type in {"local", "ollama"}:
        provider = LocalEmbedding()
    elif provider_type == "nvidia":
        provider = NvidiaEmbedding()
    elif provider_type == "cohere":
        provider = CohereEmbedding()
    else:
        raise ValueError(f"Unknown embedding_provider '{provider_type}'. Supported: local (ollama), nvidia, cohere")

    # Fail-fast validation against target index dimension
    provider.validate_dimension(settings.cohere_embed_dim)
    return provider
