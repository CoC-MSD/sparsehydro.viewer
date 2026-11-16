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


_SLOW_WARNING = r".*response needs .* h to deliver half its volume"


def quiet_slow_response_warning() -> None:
    """Filter sparsehydro's slow-bounds console warning for the process (idempotent).

    sparsehydro warns every time a calibration problem is built (each model change, each worker); the viewer
    reports the same finding once, by process and slider (:func:`slow_responses`). A permanent filter is
    used, not ``warnings.catch_warnings()``: that swaps the process-wide filter list and loses the filter when
    the live-evaluation thread and background jobs build problems at the same time. Called at import and
    again wherever problems are built, in case something reset the filters (as test runners do).
    """
    import warnings

    # a filter is (action, compiled message regex, category, module, lineno); compare the regex by its source
    if not any(f[0] == "ignore" and getattr(f[1], "pattern", None) == _SLOW_WARNING and f[2] is UserWarning
               for f in warnings.filters):
        warnings.filterwarnings("ignore", message=_SLOW_WARNING, category=UserWarning)


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


def hypervolume(F: np.ndarray, ref: np.ndarray) -> float:
    """Volume dominated by the points *F* (minimisation) and bounded by *ref*.

    Exact, by slicing along the last objective (HSO); intended for calibration fronts (up to a few hundred points
    and four objectives). Points not strictly better than *ref* in every objective contribute nothing.
    """
    F = np.atleast_2d(np.asarray(F, float))
    ref = np.asarray(ref, float)
    if F.size == 0:
        return 0.0
    F = F[np.all(np.isfinite(F), axis=1) & np.all(ref > F, axis=1)]
    if len(F) == 0:
        return 0.0
    if F.shape[1] == 1:
        return float(ref[0] - F[:, 0].min())
    F = F[np.argsort(F[:, -1], kind="stable")]
    total = 0.0
    for i in range(len(F)):
        top = F[i + 1, -1] if i + 1 < len(F) else ref[-1]
        depth = top - F[i, -1]
        if depth > 0:
            total += depth * hypervolume(F[: i + 1, :-1], ref[:-1])
    return float(total)


@dataclass
class FrontHistory:
    """Per-report front statistics of a calibration run.

    :ivar evaluations: Evaluations (or generation, when evaluations are not reported) at each report.
    :ivar size: Number of points in the reported front.
    :ivar hypervolume: Normalised hypervolume (objectives scaled to [0, 1] over the whole history, reference
        point 1.1 in every objective; higher is better), or NaN with more than four objectives.
    """

    evaluations: np.ndarray
    size: np.ndarray
    hypervolume: np.ndarray


def front_history(history: Sequence[tuple[int, int, np.ndarray]], max_objectives: int = 4) -> FrontHistory:
    """Front size and normalised hypervolume of every report in a run's history (fronts in minimisation form)."""
    fronts = [np.atleast_2d(np.asarray(F, float)) for _, _, F in history]
    x = np.array([float(n or g) for g, n, _ in history])
    size = np.array([len(F) if F.size else 0 for F in fronts], dtype=int)
    hv = np.full(len(fronts), np.nan)
    stacked = [F for F in fronts if F.size]
    if stacked and stacked[0].shape[1] <= max_objectives:
        everything = np.vstack(stacked)
        ok = np.all(np.isfinite(everything), axis=1)
        if ok.any():
            lo, hi = everything[ok].min(axis=0), everything[ok].max(axis=0)
            span = np.where(hi > lo, hi - lo, 1.0)
            ref = np.full(len(lo), 1.1)
            for i, F in enumerate(fronts):
                hv[i] = hypervolume((F - lo) / span, ref) if F.size else np.nan
    return FrontHistory(x, size, hv)


__all__ = ["ComplexityPoint", "FrontHistory", "SlowResponse", "complexity_front", "fit_statistics", "front_history",
           "hypervolume", "information_criteria", "nondominated", "slow_responses"]
