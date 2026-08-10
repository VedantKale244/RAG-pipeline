"""Tests for the config override layer: property injection, resolution order,
ContextVar isolation across thread boundaries, and non-tunable fields staying
untouched.
"""
from __future__ import annotations

import threading

import pytest

from app.config import Settings, settings
from app.selfopt import overrides
from app.selfopt.overrides import InvalidConfigError, challenger, set_champion, uninstall


@pytest.fixture(autouse=True)
def _clean_overrides():
    overrides.uninstall()
    yield
    overrides.uninstall()


def _native(name):
    """Value settings would report without any override layer — reset first."""
    overrides.uninstall()
    return getattr(settings, name)


def test_native_reads_before_install():
    # Baseline: settings reads the real .env / default value.
    assert _native("chunk_size") >= 128
    assert isinstance(_native("chunk_size"), int)


def test_non_tunable_fields_are_untouched():
    before = settings.cohere_api_key, settings.neo4j_password
    overrides.install()
    set_champion({"retrieve_top_k": 42})
    assert (settings.cohere_api_key, settings.neo4j_password) == before


def test_champion_overrides_read_after_install():
    overrides.install()
    set_champion({"retrieve_top_k": 42, "chunk_size": 512})
    assert settings.retrieve_top_k == 42
    assert settings.chunk_size == 512


def test_unset_tunable_falls_back_to_baseline():
    native_rerank = _native("rerank_top_n")
    overrides.install()
    set_champion({"retrieve_top_k": 42})
    # rerank_top_n was never overridden — reads the native value.
    assert settings.rerank_top_n == native_rerank


def test_challenger_beats_champion_inside_context_only():
    overrides.install()
    native_rerank = settings.rerank_top_n
    set_champion({"retrieve_top_k": 10})
    with challenger({"retrieve_top_k": 3}):
        assert settings.retrieve_top_k == 3
        # Partial overlay falls through to champion for unset keys.
        assert settings.rerank_top_n == native_rerank
    assert settings.retrieve_top_k == 10


def test_challenger_isolation_across_threads():
    overrides.install()
    set_champion({"retrieve_top_k": 10})
    results = {}

    def canary():
        with challenger({"retrieve_top_k": 3}, version="v-challenger"):
            results["canary"] = settings.retrieve_top_k

    t = threading.Thread(target=canary)
    t.start()
    t.join()
    assert results["canary"] == 3
    assert settings.retrieve_top_k == 10


def test_active_version_attributes_to_context_else_champion():
    overrides.install()
    set_champion({"retrieve_top_k": 10}, version="v9")
    assert overrides.active_version() == "v9"
    with challenger({"retrieve_top_k": 3}, version="v99"):
        assert overrides.active_version() == "v99"


def test_set_champion_rejects_invalid():
    overrides.install()
    with pytest.raises(InvalidConfigError):
        set_champion({"retrieve_top_k": 999})


def test_uninstall_restores_native_reads():
    native = _native("retrieve_top_k")
    overrides.install()
    set_champion({"retrieve_top_k": 42})
    assert settings.retrieve_top_k == 42
    overrides.uninstall()
    assert settings.retrieve_top_k == native