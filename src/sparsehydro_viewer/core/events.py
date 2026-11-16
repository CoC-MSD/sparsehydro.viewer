"""Event workflow: hierarchy detection, then fits of one or more model configurations.

Detection wraps :func:`sparsehydro.events.detect_event_hierarchy`. Each
:class:`EventConfig` is a model to fit to the detected events — a unit
hydrograph on rain, or any model the viewer can build (e.g. the working
model) — fitted

* **per event** with :class:`sparsehydro.calibration.GlobalSequentialFitter`
  (one parameter set per global event), and/or
* **pooled** with :class:`sparsehydro.calibration.PooledEventFitter` (one
  parameter set for all events, scored per event).

The interactive event toolbox of Hydrology-Viewer (add/split/merge events,
peak edits, smoothing pins) needs override support in sparsehydro's detection.
:class:`EventOverrides` defines the storage format so projects carry edits;
:func:`apply_overrides` applies what can be honoured after detection (deleted
global events).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .catalog import UH_KEYS, build_uh
from .options import OptionSpec

SEASONS = {12: "Winter", 1: "Winter", 2: "Winter", 3: "Spring", 4: "Spring", 5: "Spring",
           6: "Summer", 7: "Summer", 8: "Summer", 9: "Fall", 10: "Fall", 11: "Fall"}
SEASON_ORDER = ("Winter", "Spring", "Summer", "Fall")
MODES = {"per_event": "per event", "pooled": "pooled"}


def event_options() -> tuple[OptionSpec, ...]:
    """Options of the event analysis; the UH choices are every discovered UH that reads rain directly
    (each is fitted to an event with its own amplitude ``A``), extensions included."""
    from .components import NEEDS_EXCESS

    return (
        OptionSpec("uh", "choice", "peak-tail-uh", label="Unit hydrograph",
                   choices=tuple(k for k in UH_KEYS if k not in NEEDS_EXCESS),
                   doc="Shape of the default configuration (used when no configuration is listed)."),
        OptionSpec("global_event_gap_days", "float", 1.0, label="Global gap [days]", minimum=0.01, maximum=30.0,
                   doc="Maximum separation of sub-event peaks within one global event."),
        OptionSpec("peak_weight", "float", 3.0, label="Peak weight", minimum=0.0, maximum=100.0,
                   doc="Fit weight inside sub-event peak zones."),
        OptionSpec("tail_weight", "float", 1.0, label="Tail weight", minimum=0.0, maximum=100.0,
                   doc="Fit weight elsewhere inside sub-events."),
        OptionSpec("method", "choice", "Nelder-Mead", label="Optimiser",
                   choices=("Nelder-Mead", "Powell", "L-BFGS-B", "differential_evolution"),
                   doc="SciPy method for each fit (differential evolution is slower and global)."),
        OptionSpec("warm_start", "bool", True, label="Warm start",
                   doc="Start each event's fit from the previous event's parameters (per-event fits)."),
    )


@dataclass
class EventOverrides:
    """Manual edits to detected events (Hydrology-Viewer ``manual_*.json`` equivalent)."""

    deleted_global_ids: list[int] = field(default_factory=list)
    added_events: list[tuple[str, str]] = field(default_factory=list)
    bounds: dict[int, tuple[str, str]] = field(default_factory=dict)
    merged_ranges: list[tuple[str, str]] = field(default_factory=list)
    added_peaks: list[str] = field(default_factory=list)
    removed_peaks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "deleted_global_ids": self.deleted_global_ids, "added_events": self.added_events,
            "bounds": {str(k): v for k, v in self.bounds.items()}, "merged_ranges": self.merged_ranges,
            "added_peaks": self.added_peaks, "removed_peaks": self.removed_peaks,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> EventOverrides:
        d = d or {}
        return cls(
            deleted_global_ids=[int(x) for x in d.get("deleted_global_ids", [])],
            added_events=[tuple(x) for x in d.get("added_events", [])],
            bounds={int(k): tuple(v) for k, v in d.get("bounds", {}).items()},
            merged_ranges=[tuple(x) for x in d.get("merged_ranges", [])],
            added_peaks=list(d.get("added_peaks", [])), removed_peaks=list(d.get("removed_peaks", [])),
        )

    @property
    def unsupported(self) -> list[str]:
        """Edits stored but not yet applied by the library."""
        names = ["added_events", "bounds", "merged_ranges", "added_peaks", "removed_peaks"]
        return [n for n in names if getattr(self, n)]


# ---------------------------------------------------------------------------- configurations


@dataclass
class EventConfig:
    """A model to fit to the detected events.

    :ivar label: Name shown in tables and legends.
    :ivar uh: Unit hydrograph key, fitted directly on rain (``""`` when *model* is used).
    :ivar model: A :class:`~.catalog.ModelSpec` as a dict (e.g. the working model with its values).
    :ivar per_event: Fit one parameter set per global event.
    :ivar pooled: Fit one parameter set for all events.
    """

    label: str
    uh: str = ""
    model: dict | None = None
    per_event: bool = True
    pooled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"label": self.label, "uh": self.uh, "model": self.model, "per_event": self.per_event,
                "pooled": self.pooled}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> EventConfig:
        return cls(d.get("label", "model"), d.get("uh", ""), d.get("model"), bool(d.get("per_event", True)),
                   bool(d.get("pooled", False)))

    @classmethod
    def for_uh(cls, key: str, **modes) -> EventConfig:
        from .catalog import uh_label

        return cls(uh_label(key), uh=key, **modes)

    def factory(self) -> tuple[Callable[[], Any], str]:
        """``(model factory, predicted column)`` for the fitters."""
        if self.uh:
            return (lambda: build_uh(self.uh)), "Q_pred"
        from .catalog import CATALOG, ModelSpec

        spec = ModelSpec.from_dict(self.model or {})
        output = CATALOG.predicted_key(spec)
        return (lambda: CATALOG.instantiate(spec, strict=False)), output

    def model_spec(self) -> Any:
        """The configuration as a :class:`~.catalog.ModelSpec` (a UH becomes a one-component model)."""
        from .catalog import ModelSpec

        if self.uh:
            return ModelSpec.from_dict({"kind": self.uh, "options": {}, "label": self.label})
        return ModelSpec.from_dict(self.model or {})

    @property
    def modes(self) -> list[str]:
        return [m for m, on in (("per_event", self.per_event), ("pooled", self.pooled)) if on]


@dataclass
class ConfigFit:
    """Results of one configuration: the per-event summary and/or the pooled result."""

    config: EventConfig
    per_event: Any = None  # sparsehydro.calibration.SequentialFitSummary
    pooled: Any = None  # sparsehydro.calibration.PooledFitResult
    error: str = ""

    def predicted(self, mode: str) -> pd.DataFrame | None:
        if mode == "per_event" and self.per_event is not None:
            return self.per_event.global_predicted
        if mode == "pooled" and self.pooled is not None:
            return self.pooled.predicted
        return None

    def parameters(self, mode: str, global_id: int | None = None) -> dict[str, float]:
        """Fitted values: the pooled set, or the per-event set of *global_id*."""
        if mode == "pooled":
            return self.pooled.parameters if self.pooled is not None else {}
        if self.per_event is None or global_id is None:
            return {}
        for g, cal in zip(self.per_event.events, self.per_event.calibration_results):
            if int(g.global_id) == int(global_id):
                return dict(zip(cal.param_names, map(float, cal.pareto_X[0])))
        return {}

    def event_ids(self) -> list[int]:
        """Global events fitted per event by this configuration."""
        return [int(g.global_id) for g in self.per_event.events] if self.per_event is not None else []

    def kernels(self, mode: str, global_id: int | None, dt_hours: float) -> list[Any]:
        """Unit hydrographs of this configuration at its fitted values, as
        :class:`~.uh.KernelCurve` s: the one curve of a unit hydrograph configuration (labelled ``""``), or
        one per unit hydrograph component of a composed model (then a ``combined`` curve per RDII group).

        :param mode: ``"per_event"`` (the set fitted to *global_id*) or ``"pooled"``.
        :returns: ``[]`` when there is no fit for that mode and event, or the model has no unit hydrograph.
        """
        from dataclasses import replace

        from .uh import kernel_curves

        params = self.parameters(mode, global_id)
        if not params:
            return []
        if self.config.uh:
            source: Any = build_uh(self.config.uh)
            source.initialize()
            model = source
        else:
            from .catalog import CATALOG, ModelSpec

            source = CATALOG.build(ModelSpec.from_dict(self.config.model or {}), strict=False)
            model = source.model
            if not source.uh_paths:
                return []
        from .catalog import flat_names

        known = set(flat_names(model))
        for k, v in params.items():
            if k in known:
                model.apply_flat_parameter(k, v)
        curves = kernel_curves(source, dt_hours)
        return [replace(c, label="") for c in curves] if self.config.uh else curves


def _span_nse(obs: pd.DataFrame, pred: pd.DataFrame, start, end) -> float:
    sel = ((obs["datetime"] >= start) & (obs["datetime"] <= end)).to_numpy()
    o = obs.loc[sel, "stormflow"].to_numpy(float)
    p = pred.loc[sel, "Q_pred"].to_numpy(float)
    denom = float(np.sum((o - o.mean()) ** 2)) if o.size else 0.0
    return 1.0 - float(np.sum((o - p) ** 2)) / denom if denom > 0 else float("nan")


@dataclass
class EventAnalysis:
    """Detection and the fits of every configuration for one dataset.

    ``summary`` / ``uh_key`` and the per-event helpers refer to the *primary*
    fit (the first configuration fitted per event), which drives the event
    list's NSE, the details and the unit hydrograph view.
    """

    data: pd.DataFrame
    global_events: list[Any]
    sub_events: list[Any]
    savgol: Any
    summary: Any
    dt_hours: float
    uh_key: str
    options: dict[str, Any]
    fits: list[ConfigFit] = field(default_factory=list)

    def model_factory(self) -> Callable[[], Any]:
        return lambda: build_uh(self.uh_key)

    @property
    def primary(self) -> ConfigFit | None:
        return next((f for f in self.fits if f.per_event is not None), None)

    # -- tables -----------------------------------------------------------

    def fitted_ids(self) -> list[int]:
        return [int(g.global_id) for g in self.summary.events] if self.summary is not None else []

    def fit_index(self, global_id: int) -> int | None:
        if self.summary is None:
            return None
        return next((i for i, g in enumerate(self.summary.events) if int(g.global_id) == int(global_id)), None)

    def event_table(self) -> pd.DataFrame:
        cols = ["global_id", "start", "end", "window_start", "window_end", "peak", "n_sub", "fitted",
                "total_rain", "peak_flow", "nse", "season", "quarter"]
        if not self.global_events:
            return pd.DataFrame(columns=cols)
        fitted = set(self.fitted_ids())
        subs: dict[int, list[Any]] = {}
        for s in self.sub_events:
            subs.setdefault(int(s.global_id), []).append(s)
        rows = []
        for g in sorted(self.global_events, key=lambda g: g.start_datetime):
            gid = int(g.global_id)
            members = subs.get(gid, [])
            start = pd.Timestamp(g.start_datetime)
            rows.append({
                "global_id": gid, "start": start, "end": pd.Timestamp(g.end_datetime),
                "window_start": pd.Timestamp(g.window_start_datetime),
                "window_end": pd.Timestamp(g.window_end_datetime),
                "peak": pd.Timestamp(g.peak_datetime), "n_sub": len(members), "fitted": gid in fitted,
                "total_rain": float(g.total_rain),
                "peak_flow": float(max((s.peak_flow for s in members), default=np.nan)),
                "nse": self.span_nse(start, pd.Timestamp(g.end_datetime)) if gid in fitted else np.nan,
                "season": SEASONS[start.month], "quarter": f"Q{(start.month - 1) // 3 + 1}",
            })
        return pd.DataFrame(rows, columns=cols)

    def comparison_table(self) -> pd.DataFrame:
        """NSE of every configuration and mode over every global event (the event's own window), plus
        their mean: rows are events (and ``mean``), columns ``"<label> (<mode>)"``."""
        events = sorted(self.global_events, key=lambda g: g.start_datetime)
        obs = self.data[["datetime", "stormflow"]]
        out = pd.DataFrame({"global_id": [int(g.global_id) for g in events]})
        for fit in self.fits:
            for mode in fit.config.modes:
                pred = fit.predicted(mode)
                if pred is None:
                    continue
                col = f"{fit.config.label} ({MODES[mode]})"
                out[col] = [_span_nse(obs, pred, pd.Timestamp(g.start_datetime), pd.Timestamp(g.end_datetime))
                            for g in events]
        if len(out.columns) > 1:
            means = out.drop(columns="global_id").mean(numeric_only=True)
            out = pd.concat([out, pd.DataFrame([{"global_id": "mean", **means.to_dict()}])], ignore_index=True)
        return out

    def span_nse(self, start: pd.Timestamp, end: pd.Timestamp) -> float:
        return _span_nse(self.summary.global_observed, self.summary.global_predicted, start, end)

    def parameters(self, global_id: int) -> dict[str, float]:
        i = self.fit_index(global_id)
        if i is None:
            return {}
        cal = self.summary.calibration_results[i]
        return dict(zip(cal.param_names, map(float, cal.pareto_X[0])))

    def members(self, global_id: int) -> list[Any]:
        return [s for s in self.sub_events if int(s.global_id) == int(global_id)]

    def window(self, global_id: int) -> tuple[pd.Timestamp, pd.Timestamp]:
        g = next(g for g in self.global_events if int(g.global_id) == int(global_id))
        return pd.Timestamp(g.window_start_datetime), pd.Timestamp(g.window_end_datetime)

    def predicted(self) -> pd.DataFrame:
        return self.summary.global_predicted

    def weights(self) -> np.ndarray:
        """Fit weight per time step of the whole record: the peak weight from rise start to tail start of
        each sub-event, the tail weight elsewhere inside sub-events, zero outside."""
        t = self.data["datetime"].to_numpy()
        w = np.zeros(len(t))
        pw, tw = float(self.options["peak_weight"]), float(self.options["tail_weight"])

        def span(a, b) -> slice:
            return slice(int(np.searchsorted(t, np.datetime64(pd.Timestamp(a)))),
                         int(np.searchsorted(t, np.datetime64(pd.Timestamp(b)), side="right")))

        for s in self.sub_events:
            z = span(s.start_datetime, s.end_datetime)
            w[z] = np.maximum(w[z], tw)
            z = span(s.rise_start_datetime, s.tail_start_datetime)
            w[z] = np.maximum(w[z], pw)
        return w


# ---------------------------------------------------------------------------- running


def run_event_analysis(data: pd.DataFrame, options: dict[str, Any], overrides: EventOverrides | None = None,
                       should_stop: Callable[[], bool] = lambda: False,
                       progress: Callable[[int, int, str], None] | None = None,
                       configs: list[EventConfig] | None = None) -> EventAnalysis:
    """Detect events, then fit every configuration (per event and/or pooled).

    :param data: Standardised frame (``datetime``, ``rain``, ``stormflow``; other columns such as
        ``temperature_c`` are passed to the models).
    :param options: Values for :func:`event_options`.
    :param overrides: Manual edits; see :class:`EventOverrides`.
    :param should_stop: Checked between fits and between events; returning ``True`` raises
        :class:`InterruptedError`.
    :param progress: ``progress(done, total, text)`` over all fits; ``total`` is 0 while detecting.
    :param configs: Models to fit; default: the options' unit hydrograph, per event.
    """
    from sparsehydro.calibration import GlobalSequentialFitter, PooledEventFitter
    from sparsehydro.events import detect_event_hierarchy

    from .catalog import CATALOG
    from .data import dt_hours
    from .options import resolve_options

    report = progress or (lambda i, n, text: None)
    opts = resolve_options(event_options(), options)
    configs = list(configs) if configs else [EventConfig.for_uh(opts["uh"])]
    df = CATALOG.prepare_frame(data.reset_index(drop=True).copy())
    report(0, 0, "detecting events")
    global_events, sub_events, savgol = detect_event_hierarchy(
        df[["datetime", "rain", "stormflow"]], global_event_gap_days=opts["global_event_gap_days"])
    global_events, sub_events = apply_overrides(global_events, sub_events, overrides)
    if should_stop():
        raise InterruptedError("cancelled")
    n = len(global_events)
    total = sum(n * c.per_event + c.pooled for c in configs) or 1
    done = [0]

    def step(text: str) -> None:
        if should_stop():
            raise InterruptedError("cancelled")
        report(done[0], total, text)

    fits: list[ConfigFit] = []
    for config in configs:
        fit = ConfigFit(config)
        try:
            factory, output = config.factory()
            if config.per_event:
                base = done[0]

                def per_event_progress(i: int, _n: int, text: str, base=base, label=config.label) -> None:
                    done[0] = base + i
                    step(f"{label}: {text}")

                fit.per_event = GlobalSequentialFitter(factory, df, global_events, sub_events, output).fit(
                    method=opts["method"], peak_weight=opts["peak_weight"], tail_weight=opts["tail_weight"],
                    verbose=False, warm_start=opts["warm_start"], progress=per_event_progress,
                    should_stop=should_stop)
                done[0] = base + n
            if config.pooled:
                step(f"{config.label}: pooled fit over {n} events")
                fit.pooled = PooledEventFitter(factory, df, global_events, sub_events, output).fit(
                    method=opts["method"], peak_weight=opts["peak_weight"], tail_weight=opts["tail_weight"])
                done[0] += 1
        except InterruptedError:
            raise
        except Exception as exc:  # noqa: BLE001 - one configuration failing does not lose the others
            fit.error = f"{type(exc).__name__}: {exc}"
        fits.append(fit)
    report(total, total, "done")
    primary = next((f for f in fits if f.per_event is not None), None)
    return EventAnalysis(df, global_events, sub_events, savgol, primary.per_event if primary else None,
                         dt_hours(df), primary.config.uh if primary else "", opts, fits)


def apply_overrides(global_events: list[Any], sub_events: list[Any],
                    overrides: EventOverrides | None) -> tuple[list[Any], list[Any]]:
    if overrides is None or not overrides.deleted_global_ids:
        return global_events, sub_events
    gone = set(overrides.deleted_global_ids)
    return ([g for g in global_events if int(g.global_id) not in gone],
            [s for s in sub_events if int(s.global_id) not in gone])


__all__ = ["MODES", "SEASON_ORDER", "ConfigFit", "EventAnalysis", "EventConfig", "EventOverrides", "apply_overrides",
           "event_options", "run_event_analysis"]
