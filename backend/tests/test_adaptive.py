"""Unit tests for the adaptive-embedding math — pure functions, no GPU/graph needed."""
from __future__ import annotations

import numpy as np

from app.core.adaptive import _cosine


class TestCosine:
    def test_identical_vectors(self):
        v = np.array([1.0, 2.0, 3.0])
        assert abs(_cosine(v, v) - 1.0) < 1e-6

    def test_opposite_vectors(self):
        v = np.array([1.0, 0.0])
        assert abs(_cosine(v, -v) + 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        a = np.array([1.0, 0.0])
        b = np.array([0.0, 1.0])
        assert abs(_cosine(a, b)) < 1e-6

    def test_zero_vector_is_safe(self):
        z = np.zeros(3)
        result = _cosine(z, np.array([1.0, 1.0, 1.0]))
        assert abs(result) < 1e-3

    def test_scale_invariant(self):
        a = np.array([2.0, 4.0])
        b = np.array([1.0, 2.0])
        assert abs(_cosine(a, b) - 1.0) < 1e-6
