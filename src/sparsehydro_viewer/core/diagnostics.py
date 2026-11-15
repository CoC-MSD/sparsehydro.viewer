"""Parsimony diagnostics: performance against parameter count.

These belong in ``sparsehydro.calibration.diagnostics`` (plan item L7) and live
here until the library provides them.  Everything is plain numpy.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np


def nondominated(F: np.ndarray) -> np.ndarray:
    """Boolean mask of non-dominated rows of *F* (all columns minimised).

    :param F: ``(n, m)`` array.
    :returns: ``(n,)`` mask; rows with NaN are treated as dominated.
    """
    F = np.atleast_2d(np.asarray(F, dtype=float))
    n = F.shape[0]
    ok = ~np.isnan(F).any(axis=1)
    mask = ok.copy()
    for i in range(n):
        if not mask[i]:
            continue
        others = F[ok]
        dominated = np.all(others <= F[i], axis=1) & np.any(others < F[i], axis=1)
        if dominated.any():
            mask[i] = False
    return mask


def information_criteria(sse: float, n: int, k: int) -> dict[str, float]:
    """Gaussian-likelihood AIC, AICc and BIC from a sum of squared errors.

    ``AIC = n ln(SSE/n) + 2k``; ``AICc`` adds ``2k(k+1)/(n-k-1)``;
    ``BIC = n ln(SSE/n) + k ln n``.  Only differences between models fitted to
    the same observations are meaningful.  Autocorrelated residuals make the
    effective ``n`` smaller than the number of time steps, so treat these as a
    ranking aid rather than a test.

    :param sse: Sum of squared residuals.
    :param n: Number of observations.
    :param k: Number of calibrated parameters.
    """
    if n <= 0 or sse <= 0:
        return {"AIC": float("nan"), "AICc": float("nan"), "BIC": float("nan")}
    base = n * np.log(sse / n)
    aic = base + 2 * k
    aicc = aic + (2 * k * (k + 1) / (n - k - 1) if n - k - 1 > 0 else np.inf)
    return {"AIC": float(aic), "AICc": float(aicc), "BIC": float(base + k * np.log(n))}


def fit_statistics(observed: np.ndarray, predicted: np.ndarray, k: int) -> dict[str, float]:
    """Error statistics and information criteria over the finite overlap."""
    o = np.asarray(observed, dtype=float)
    p = np.asarray(predicted, dtype=float)
    sel = np.isfinite(o) & np.isfinite(p)
    o, p = o[sel], p[sel]
    n = int(o.size)
    if n == 0:
        return {"n": 0, "SSE": float("nan"), "RMSE": float("nan"), "NSE": float("nan"),
                "AIC": float("nan"), "AICc": float("nan"), "BIC": float("nan")}
    sse = float(np.sum((o - p) ** 2))
    denom = float(np.sum((o - o.mean()) ** 2))
    out = {"n": n, "SSE": sse, "RMSE": float(np.sqrt(sse / n)),
           "NSE": 1.0 - sse / denom if denom > 0 else float("nan")}
    out.update(information_criteria(sse, n, k))
    return out


@dataclass(frozen=True)
class ComplexityPoint:
    """One model on the complexity-performance plane."""

    key: str
    label: str
    n_params: int
    score: float  # minimisation form


def complexity_front(points: Sequence[ComplexityPoint]) -> list[ComplexityPoint]:
    """Models not beaten by a simpler-or-equal model with a better-or-equal score.

    Sorted by parameter count, so it can be drawn as a step line.
    """
    if not points:
        return []
    F = np.array([[p.n_params, p.score] for p in points], dtype=float)
    mask = nondominated(F)
    return sorted((p for p, m in zip(points, mask) if m), key=lambda p: (p.n_params, p.score))


__all__ = ["ComplexityPoint", "complexity_front", "fit_statistics", "information_criteria", "nondominated"]
