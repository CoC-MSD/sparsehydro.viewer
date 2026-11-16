"""Bring projects saved with step-based unit hydrographs up to the hours-based library.

sparsehydro's unit hydrographs took their time parameters in *time steps*
under other names, and scaled predictions by ``dt``; they now use hours and
``Q = A * conv(rain, kernel)``. The conversions are exact for the shapes
(sampling of the kernel differs slightly, so re-simulated scores can move in
the last digits):

=================  ==================================================
gamma-uh           ``alpha = tt + 1``, ``theta = tp * dt``
gamma-delay-uh     as gamma, plus ``td = td * dt``
nash-uh            ``n`` unchanged, ``K = k * dt``
triangle-uh        ``Tp = tp * dt``, ``Tb = tt * dt``
rectangle-uh       ``Tr = tr * dt``
decay-uh           ``K = -dt / ln(alpha)`` (per-step ratio to hours)
peak-tail-uh       ``peak_Tp``, ``peak_Tb``, ``tail_alpha = tail_tt + 1``,
                   ``tail_theta``, ``td`` as above; ``w`` unchanged
amplitude ``A``    ``A * dt`` where ``A`` is the UH's own amplitude (not
                   inside an RDII component, which uses ``R_i``)
=================  ==================================================

RTK triangles were already in hours and are unchanged. ``dt`` is the time
step of the dataset the values were fitted on.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Callable
from typing import Any

import numpy as np

from .catalog import ModelSpec, ParameterState

#: Project-file marker: 2 = hours-based unit hydrographs.
UH_SCHEMA = 2

Convert = Callable[[float, float], float]


def _mul(v: float, dt: float) -> float:
    return v * dt


def _plus_one(v: float, _dt: float) -> float:
    return v + 1.0


def _ratio_to_hours(v: float, dt: float) -> float:
    if v <= 0.0:
        return 0.0
    if v >= 1.0:
        return math.inf
    return -dt / math.log(v)


_GAMMA = {"tt": ("alpha", _plus_one), "tp": ("theta", _mul)}

#: Old local name -> (new local name, conversion) per component type.
RENAMES: dict[str, dict[str, tuple[str, Convert]]] = {
    "gamma-uh": dict(_GAMMA),
    "gamma-delay-uh": {**_GAMMA, "td": ("td", _mul)},
    "nash-uh": {"k": ("K", _mul)},
    "triangle-uh": {"tp": ("Tp", _mul), "tt": ("Tb", _mul)},
    "rectangle-uh": {"tr": ("Tr", _mul)},
    "decay-uh": {"alpha": ("K", _ratio_to_hours)},
    "peak-tail-uh": {"peak_tp": ("peak_Tp", _mul), "peak_tt": ("peak_Tb", _mul),
                     "tail_tt": ("tail_alpha", _plus_one), "tail_tp": ("tail_theta", _mul), "td": ("td", _mul)},
}


def renames_for(spec: ModelSpec) -> dict[str, tuple[str, Convert]]:
    """Flat old name -> (flat new name, conversion) for every unit hydrograph in *spec*'s tree."""
    from .components import build

    built = build(spec.root)
    out: dict[str, tuple[str, Convert]] = {}
    for _label, child, prefix, amp_name in built.uh_paths:
        key = getattr(child, "model_name", "")
        for old, (new, fn) in RENAMES.get(key, {}).items():
            out[f"{prefix}{old}"] = (f"{prefix}{new}", fn)
        # The UH's own amplitude A scales the flow for a bare UH (amp_name is its A) and for excess -> UH
        # (amp_name None: the composite keeps uh_A); inside an RDII component the amplitude is R_i instead.
        if getattr(type(child), "_amplitude_param_name", None) == "A" and amp_name in (None, f"{prefix}A"):
            out[f"{prefix}A"] = (f"{prefix}A", _mul)
    return out


def _finite(x: float) -> float | None:
    return float(x) if x is not None and math.isfinite(x) else None


def migrate_model_spec(spec: ModelSpec, dt_hours: float) -> ModelSpec:
    """Copy of *spec* with step-based UH overrides converted to hours."""
    table = renames_for(spec)
    out = copy.deepcopy(spec)
    params: dict[str, ParameterState] = {}
    for name, state in spec.parameters.items():
        if name not in table:
            params[name] = copy.deepcopy(state)
            continue
        new, fn = table[name]

        def conv(v: float | None, fn: Convert = fn) -> float | None:
            return _finite(fn(v, dt_hours)) if v is not None else None

        params[new] = ParameterState(conv(state.value), conv(state.lower), conv(state.upper), state.calibrate)
        if fn is _ratio_to_hours:  # bounds of a ratio do not map to sensible hour bounds
            params[new].lower = params[new].upper = None
    out.parameters = params
    return out


def migrate_values(spec: ModelSpec, values: dict[str, float], dt_hours: float) -> dict[str, float]:
    """Flat ``{name: value}`` of *spec* converted to the hours-based names."""
    table = renames_for(spec)
    out = {}
    for name, v in values.items():
        if name in table:
            new, fn = table[name]
            converted = _finite(fn(float(v), dt_hours))
            if converted is not None:
                out[new] = converted
        else:
            out[name] = float(v)
    return out


def migrate_run(run: Any, dt_hours: float) -> bool:
    """Convert a :class:`~.runs.RunRecord` in place; ``True`` if anything changed."""
    table = renames_for(run.model)
    if not any(n in table for n in list(run.param_names) + list(run.fixed_values) + list(run.model.parameters)):
        return False
    X = np.array(run.pareto_X, dtype=float, copy=True)
    names = list(run.param_names)
    for j, name in enumerate(run.param_names):
        if name in table and X.ndim == 2 and X.shape[1] > j:
            new, fn = table[name]
            X[:, j] = [fn(float(v), dt_hours) for v in X[:, j]]
            names[j] = new
        elif name in table:
            names[j] = table[name][0]
    run.param_names = names
    run.pareto_X = X
    run.fixed_values = migrate_values(run.model, run.fixed_values, dt_hours)
    run.model = migrate_model_spec(run.model, dt_hours)
    note = "Converted from step-based unit hydrograph parameters; scores are from the earlier library."
    run.message = f"{run.message}  {note}".strip() if run.message else note
    return True


def dt_hours_of(frame) -> float | None:
    """Median time step of a dataset frame, in hours."""
    if frame is None or len(frame) < 2:
        return None
    t = np.asarray(frame["datetime"], dtype="datetime64[ns]").astype("int64")
    dt = float(np.median(np.diff(t))) / 3.6e12
    return dt if dt > 0 else None


def migrate_project(project: Any) -> list[str]:
    """Convert a project's models, working model and runs in place.

    :returns: Messages for anything that could not be converted (a run whose
        dataset is missing has no time step).
    """
    notes: list[str] = []
    dts: dict[str, float | None] = {}

    def dt_for(name: str) -> float | None:
        if name not in dts:
            try:
                dts[name] = dt_hours_of(project.frame(name))
            except Exception:  # noqa: BLE001 - a dataset that cannot be read has no time step
                dts[name] = None
        return dts[name]

    current = project.ui_state.get("dataset") or (project.datasets[0].name if project.datasets else "")
    default_dt = dt_for(current) if current else None
    if default_dt is None:
        default_dt = next((d for d in (dt_for(ds.name) for ds in project.datasets) if d), None)
    for run in project.runs:
        dt = dt_for(run.dataset) or default_dt
        if dt is None:
            if renames_for(run.model):
                notes.append(f"Run {run.label!r}: dataset {run.dataset!r} is missing, so its step-based unit "
                             "hydrograph parameters could not be converted to hours.")
            continue
        migrate_run(run, dt)
    if default_dt is not None:
        project.models = [migrate_model_spec(m, default_dt) for m in project.models]
        if isinstance(project.ui_state.get("model"), dict):
            spec = ModelSpec.from_dict(project.ui_state["model"])
            project.ui_state["model"] = migrate_model_spec(spec, default_dt).to_dict()
    elif any(renames_for(m) for m in project.models):
        notes.append("No dataset is available to read the time step from, so model parameters were reset "
                     "to the library defaults.")
        project.models = [ModelSpec(m.root, {}, m.label) for m in project.models]
    return notes


__all__ = ["RENAMES", "UH_SCHEMA", "dt_hours_of", "migrate_model_spec", "migrate_project", "migrate_run",
           "migrate_values", "renames_for"]
