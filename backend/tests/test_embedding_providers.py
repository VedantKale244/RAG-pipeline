"""Unit tests for provider-agnostic EmbeddingProvider layer.

Verifies contract compliance, provider class hierarchy (LocalEmbedding, NvidiaEmbedding, CohereEmbedding),
configurable endpoints (Ollama/NVIDIA), and fail-fast dimension validation.
"""
from unittest.mock import MagicMock, patch

import pytest
from app.config import settings
from app.core.embedding_provider import (
    CohereEmbedding,
    CohereEmbeddingProvider,
    DimensionMismatchError,
    EmbeddingProvider,
    EmbeddingUnavailable,
    LocalEmbedding,
    NvidiaEmbedding,
    NvidiaEmbeddingProvider,
    OllamaEmbeddingProvider,
    get_embedding_provider,
)


class TestEmbeddingProviderContract:
    def test_cohere_embedding_class_contract(self):
        provider = CohereEmbedding(model="embed-english-v3.0", api_key="test_key", dim=1024)
        assert isinstance(provider, EmbeddingProvider)
        assert provider.provider_name == "cohere"
        assert provider.dimension == 1024

        mock_embeddings_lc = MagicMock()
        mock_embeddings_lc.embed_query.return_value = [0.1] * 1024
        mock_embeddings_lc.embed_documents.return_value = [[0.2] * 1024, [0.3] * 1024]

        with patch.object(provider, "_get_langchain_embeddings", return_value=mock_embeddings_lc):
            query_vec = provider.embed_query("test query")
            assert len(query_vec) == 1024
            assert query_vec[0] == 0.1

            doc_vecs = provider.embed_documents(["doc1", "doc2"])
            assert len(doc_vecs) == 2
            assert len(doc_vecs[0]) == 1024

    def test_local_embedding_class_contract(self):
        provider = LocalEmbedding(
            base_url="http://host.docker.internal:11434",
            model="nomic-embed-text",
            dim=1024,
        )
        assert isinstance(provider, EmbeddingProvider)
        assert provider.provider_name == "local"
        assert provider.dimension == 1024

        mock_response = {"embedding": [0.5] * 1024}
        with patch.object(provider, "_post_api", return_value=mock_response) as mock_post:
            query_vec = provider.embed_query("test prompt")
            assert len(query_vec) == 1024
            assert query_vec[0] == 0.5
            mock_post.assert_called_with("embeddings", {"model": "nomic-embed-text", "prompt": "test prompt"})

    def test_nvidia_embedding_class_contract(self):
        provider = NvidiaEmbedding(
            api_key="nvapi-test-key",
            endpoint="https://custom.nim.nvidia.com/v1",
            model="nvidia/nv-embed-v2",
            dim=1024,
        )
        assert isinstance(provider, EmbeddingProvider)
        assert provider.provider_name == "nvidia"
        assert provider.dimension == 1024

        mock_query_response = {"data": [{"embedding": [0.8] * 1024}]}
        with patch.object(provider, "_post_api", return_value=mock_query_response) as mock_post:
            query_vec = provider.embed_query("nvidia search query")
            assert len(query_vec) == 1024
            mock_post.assert_called_with({"input": ["nvidia search query"], "model": "nvidia/nv-embed-v2", "input_type": "query"})

    def test_backward_compatibility_aliases(self):
        assert OllamaEmbeddingProvider is LocalEmbedding
        assert CohereEmbeddingProvider is CohereEmbedding
        assert NvidiaEmbeddingProvider is NvidiaEmbedding


class TestFailFastDimensionValidation:
    def test_dimension_mismatch_raises_error(self):
        provider = LocalEmbedding(dim=768)
        with pytest.raises(DimensionMismatchError) as exc_info:
            provider.validate_dimension(1024)
        assert "produces 768-dim vectors" in str(exc_info.value)
        assert "requires 1024-dim vectors" in str(exc_info.value)

    def test_factory_dimension_validation_triggers_fail_fast(self, monkeypatch):
        monkeypatch.setattr(settings, "embedding_provider", "local")
        monkeypatch.setattr(settings, "ollama_embed_dim", 384)
        monkeypatch.setattr(settings, "cohere_embed_dim", 1024)

        with pytest.raises(DimensionMismatchError):
            get_embedding_provider()


class TestProviderFactoryAndSwitching:
    def test_factory_defaults_to_cohere(self, monkeypatch):
        monkeypatch.setattr(settings, "embedding_provider", "cohere")
        provider = get_embedding_provider()
        assert provider.provider_name == "cohere"
        assert isinstance(provider, CohereEmbedding)

    def test_factory_instantiates_local(self, monkeypatch):
        monkeypatch.setattr(settings, "embedding_provider", "local")
        monkeypatch.setattr(settings, "ollama_embed_dim", 1024)
        provider = get_embedding_provider()
        assert provider.provider_name == "local"
        assert isinstance(provider, LocalEmbedding)

    def test_factory_instantiates_ollama_alias(self, monkeypatch):
        monkeypatch.setattr(settings, "embedding_provider", "ollama")
        monkeypatch.setattr(settings, "ollama_embed_dim", 1024)
        provider = get_embedding_provider()
        assert provider.provider_name == "local"
        assert isinstance(provider, LocalEmbedding)

    def test_factory_instantiates_nvidia(self, monkeypatch):
        monkeypatch.setattr(settings, "embedding_provider", "nvidia")
        monkeypatch.setattr(settings, "nvidia_embed_dim", 1024)
        provider = get_embedding_provider()
        assert provider.provider_name == "nvidia"
        assert isinstance(provider, NvidiaEmbedding)

    def test_factory_unknown_provider_raises_value_error(self):
        with pytest.raises(ValueError) as exc:
            get_embedding_provider("unknown_provider")
        assert "Unknown embedding_provider 'unknown_provider'" in str(exc.value)


class TestProviderErrorHandling:
    def test_cohere_quota_exhausted_raises_embedding_unavailable(self):
        provider = CohereEmbedding()
        mock_embeddings_lc = MagicMock()
        mock_embeddings_lc.embed_query.side_effect = Exception("You have exceeded your monthly quota")

        with patch.object(provider, "_get_langchain_embeddings", return_value=mock_embeddings_lc):
            with pytest.raises(EmbeddingUnavailable) as exc:
                provider.embed_query("test query")
            assert "Cohere API quota exhausted" in str(exc.value)

    def test_local_unreachable_raises_embedding_unavailable(self):
        provider = LocalEmbedding(base_url="http://invalid.host:9999")
        with pytest.raises(EmbeddingUnavailable) as exc:
            provider.embed_query("test query")
        assert "Local embedding connection failed" in str(exc.value)

    def test_nvidia_missing_key_raises_embedding_unavailable(self):
        provider = NvidiaEmbedding(api_key="")
        with pytest.raises(EmbeddingUnavailable) as exc:
            provider.embed_query("test query")
        assert "NVIDIA API key missing" in str(exc.value)
