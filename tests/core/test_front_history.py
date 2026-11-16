"""Front statistics shown in the Calibrate convergence chart."""

from __future__ import annotations

import numpy as np
import pytest

from sparsehydro_viewer.core.diagnostics import front_history, hypervolume


def test_hypervolume_of_simple_fronts() -> None:
    ref = np.array([1.0, 1.0])
    assert hypervolume(np.array([[0.5, 0.5]]), ref) == pytest.approx(0.25)
    # boxes [0,1]x[0.5,1] and [0.5,1]x[0,1] (0.5 each) overlap in [0.5,1]x[0.5,1] (0.25): union 0.75
    two = np.array([[0.0, 0.5], [0.5, 0.0]])
    assert hypervolume(two, ref) == pytest.approx(0.75)
    # a dominated point adds nothing; a point beyond the reference is ignored
    assert hypervolume(np.vstack([two, [[0.6, 0.6]], [[1.2, 0.0]]]), ref) == pytest.approx(0.75)
    assert hypervolume(np.array([[0.5, 0.5, 0.5]]), np.ones(3)) == pytest.approx(0.125)
    assert hypervolume(np.empty((0, 2)), ref) == 0.0


def test_hypervolume_matches_monte_carlo_in_three_objectives() -> None:
    rng = np.random.default_rng(3)
    F = rng.random((12, 3))
    exact = hypervolume(F, np.ones(3))
    samples = rng.random((200_000, 3))
    dominated = np.zeros(len(samples), bool)
    for p in F:
        dominated |= np.all(samples >= p, axis=1)
    assert exact == pytest.approx(dominated.mean(), abs=5e-3)


def test_front_history_improves_as_the_front_converges() -> None:
    history = [(1, 10, np.array([[0.9, 0.9]])),
               (2, 20, np.array([[0.5, 0.9], [0.9, 0.5]])),
               (3, 30, np.array([[0.1, 0.9], [0.4, 0.4], [0.9, 0.1]]))]
    h = front_history(history)
    assert list(h.evaluations) == [10, 20, 30] and list(h.size) == [1, 2, 3]
    assert np.all(np.diff(h.hypervolume) > 0)
    assert np.isnan(front_history([(1, 0, np.zeros((2, 5)))]).hypervolume[0])  # too many objectives
