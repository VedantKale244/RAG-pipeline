"""Tests for overrides.validate() — the whitelist gate between the optimizer and
writing neo4j_password (or any other secret) into a config.

``validate()`` is the only thing standing between the experiment engine and the
settings object. These pin the rejections so a bad proposal never reaches the
offline gate.
"""
from __future__ import annotations

import pytest

from app.selfopt.overrides import InvalidConfigError, TUNABLES, validate


def test_valid_delta_passes():
    validate({"retrieve_top_k": 12, "rerank_min_score": 0.2})


def test_empty_dict_is_a_valid_noop_delta():
    # propose() can legitimately produce a no-op delta after clamping
    # (e.g. every knob already at its boundary). It must not crash.
    validate({})


def test_unknown_key_rejected_never_silently_ignored():
    with pytest.raises(InvalidConfigError, match="unknown tunable"):
        validate({"cohere_api_key": "sk-1234", "retrieve_top_k": 10})


def test_secret_field_is_not_tunable():
    from app.selfopt.overrides import TUNABLES
    assert "neo4j_password" not in TUNABLES
    with pytest.raises(InvalidConfigError):
        validate({"neo4j_password": "pwned", "retrieve_top_k": 10})


@pytest.mark.parametrize(
    "name,value",
    [
        ("chunk_size", 64),           # below low bound
        ("chunk_size", 4096),         # above high bound
        ("retrieve_top_k", 0),        # below low bound
        ("graphsage_epochs", 100),    # above high bound
        ("expand_hops", 7),           # above high bound
        ("rerank_min_score", 1.0),    # above high bound
    ],
)
def test_out_of_range_rejected(name, value):
    with pytest.raises(InvalidConfigError, match="out of range"):
        validate({name: value})


def test_int_fields_reject_float():
    with pytest.raises(InvalidConfigError, match="integer"):
        validate({"chunk_size": 512.5})


def test_non_field_rejected():
    with pytest.raises(InvalidConfigError):
        validate({"bogus_knob": 1})


def test_invariant_chunk_overlap_lt_chunk_size():
    with pytest.raises(InvalidConfigError, match="chunk_overlap"):
        validate({"chunk_size": 128, "chunk_overlap": 300})


def test_invariant_rerank_top_n_le_retrieve_top_k():
    with pytest.raises(InvalidConfigError, match="rerank_top_n"):
        validate({"retrieve_top_k": 3, "rerank_top_n": 5})


def test_invariant_not_tripped_by_absent_partner():
    # Only one side present: the invariant has nothing to compare, must pass.
    validate({"chunk_overlap": 300})
    validate({"chunk_size": 128})
    validate({"rerank_top_n": 20})
    validate({"retrieve_top_k": 3})