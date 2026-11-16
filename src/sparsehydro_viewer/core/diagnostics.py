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


@dataclass(frozen=True)
class SlowResponse:
    """A unit hydrograph whose bounds allow responses slower than the data.

    :ivar label: The process, as the viewer names it (e.g. ``"wet › UH 2: Gamma UH"``).
    :ivar median_hours: Time to deliver half the volume at the upper bounds.
    :ivar parameters: Flat names of the calibrated time and shape parameters.
    """

    label: str
    median_hours: float
    record_hours: float
    parameters: tuple[str, ...]

    def message(self) -> str:
        names = ", ".join(self.parameters)
        return (f"{self.label}: at the upper bounds of {names} the response needs {self.median_hours:.0f} h to "
                f"deliver half its volume, but the calibration period covers {self.record_hours:.0f} h. Much of "
                "the search range then predicts almost no flow and the optimiser can stall there; lower those "
                "upper bounds to what is plausible for the site.")


def slow_responses(built, record_hours: float, fraction: float = 0.5) -> list[SlowResponse]:
    """Unit hydrographs of a built model whose search range allows responses too slow for the record.

    The check is sparsehydro's (``UnitHydrographBase.slowest_median_hours``),
    applied to each unit hydrograph with the bounds and calibrate flags its
    parent gives it, so messages name the process and slider as the viewer
    shows them.
    """
    import copy

    if not record_hours > 0:
        return []
    parent = built.model
    names = set(parent.scalar_parameter_names)
    out = []
    for label, child, prefix, _amp in built.uh_paths:
        if not hasattr(child, "slowest_median_hours"):
            continue
        uh = copy.deepcopy(child)
        if not uh.is_initialized():
            uh.initialize()
        for name in uh.scalar_parameter_names:
            full = f"{prefix}{name}"
            if full in names:
                src = parent.get_scalar_parameter(full)
                uh.get_scalar_parameter(name).update(lower_bound=src.lower_bound, upper_bound=src.upper_bound,
                                                     value=min(max(src.value, src.lower_bound), src.upper_bound),
                                                     calibrate=src.calibrate)
        try:
            median = float(uh.slowest_median_hours())
        except Exception:  # noqa: BLE001 - a diagnostic never breaks the model
            continue
        if median > fraction * record_hours:
            timing = [f"{prefix}{n}" for n, p in uh.timing_parameters().items()
                      if p.calibrate and f"{prefix}{n}" in names]
            if timing:
                out.append(SlowResponse(label, median, float(record_hours), tuple(timing)))
    return out


__all__ = ["ComplexityPoint", "SlowResponse", "complexity_front", "fit_statistics", "information_criteria",
           "nondominated", "slow_responses"]
