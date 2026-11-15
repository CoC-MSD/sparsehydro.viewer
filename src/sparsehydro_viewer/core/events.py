"""Event workflow: hierarchy detection and one unit hydrograph per global event.

Wraps :func:`sparsehydro.events.detect_event_hierarchy` and
:class:`sparsehydro.models.unithydrograph.GlobalSequentialFitter` and derives
the tables and per-event windows the Events workspace shows.

The interactive event toolbox of Hydrology-Viewer (add/delete/split/merge
events, peak edits, smoothing pins) needs override support in sparsehydro's
detection (plan item L8).  :class:`EventOverrides` defines the storage format
now so projects can carry edits; :func:`apply_overrides` applies the subset that
can be honoured after detection (deleted global events).
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

EVENT_OPTIONS: tuple[OptionSpec, ...] = (
    OptionSpec("uh", "choice", "peak-tail-uh", label="Unit hydrograph",
               choices=tuple(k for k in UH_KEYS if k != "rtk-triangle"),  # fitted with its own amplitude A
               doc="Shape fitted to each global event."),
    OptionSpec("global_event_gap_days", "float", 1.0, label="Global gap [days]", minimum=0.01, maximum=30.0,
               doc="Maximum separation of sub-event peaks within one global event."),
    OptionSpec("peak_weight", "float", 3.0, label="Peak weight", minimum=0.0, maximum=100.0,
               doc="Fit weight inside sub-event peak zones."),
    OptionSpec("tail_weight", "float", 1.0, label="Tail weight", minimum=0.0, maximum=100.0,
               doc="Fit weight elsewhere inside sub-events."),
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


@dataclass
class EventAnalysis:
    """Detection and per-event fit results for one dataset."""

    data: pd.DataFrame
    global_events: list[Any]
    sub_events: list[Any]
    savgol: Any
    summary: Any
    dt_hours: float
    uh_key: str
    options: dict[str, Any]

    def model_factory(self) -> Callable[[], Any]:
        return lambda: build_uh(self.uh_key)

    # -- tables -----------------------------------------------------------

    def fitted_ids(self) -> list[int]:
        return [int(g.global_id) for g in self.summary.events]

    def fit_index(self, global_id: int) -> int | None:
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

    def span_nse(self, start: pd.Timestamp, end: pd.Timestamp) -> float:
        obs = self.summary.global_observed
        pred = self.summary.global_predicted
        sel = ((obs["datetime"] >= start) & (obs["datetime"] <= end)).to_numpy()
        o = obs.loc[sel, "stormflow"].to_numpy(float)
        p = pred.loc[sel, "Q_pred"].to_numpy(float)
        denom = float(np.sum((o - o.mean()) ** 2)) if o.size else 0.0
        return 1.0 - float(np.sum((o - p) ** 2)) / denom if denom > 0 else float("nan")

    def parameters(self, global_id: int) -> dict[str, float]:
        i = self.fit_index(global_id)
        if i is None:
            return {}
        cal = self.summary.calibration_results[i]
        return dict(zip(cal.param_names, map(float, cal.pareto_X[0])))

    def fitted_model(self, global_id: int) -> Any | None:
        params = self.parameters(global_id)
        if not params:
            return None
        m = build_uh(self.uh_key)
        m.initialize()
        for k, v in params.items():
            m.apply_flat_parameter(k, v)
        return m

    def members(self, global_id: int) -> list[Any]:
        return [s for s in self.sub_events if int(s.global_id) == int(global_id)]

    def window(self, global_id: int) -> tuple[pd.Timestamp, pd.Timestamp]:
        g = next(g for g in self.global_events if int(g.global_id) == int(global_id))
        return pd.Timestamp(g.window_start_datetime), pd.Timestamp(g.window_end_datetime)

    def predicted(self) -> pd.DataFrame:
        return self.summary.global_predicted


def run_event_analysis(data: pd.DataFrame, options: dict[str, Any], overrides: EventOverrides | None = None,
                       should_stop: Callable[[], bool] = lambda: False) -> EventAnalysis:
    """Detect events and fit one unit hydrograph per global event.

    :param data: Standardised frame (``datetime``, ``rain``, ``stormflow``).
    :param options: Values for :data:`EVENT_OPTIONS`.
    :param overrides: Manual edits; see :class:`EventOverrides`.
    :param should_stop: Checked between detection and fitting.
    """
    from sparsehydro.events import detect_event_hierarchy
    from sparsehydro.models.unithydrograph import GlobalSequentialFitter

    from .data import dt_hours
    from .options import resolve_options

    opts = resolve_options(EVENT_OPTIONS, options)
    df = data[["datetime", "rain", "stormflow"]].copy()
    global_events, sub_events, savgol = detect_event_hierarchy(df, global_event_gap_days=opts["global_event_gap_days"])
    global_events, sub_events = apply_overrides(global_events, sub_events, overrides)
    if should_stop():
        raise InterruptedError("cancelled")
    uh_key = opts["uh"]
    summary = GlobalSequentialFitter(lambda: build_uh(uh_key), df, global_events, sub_events).fit(
        peak_weight=opts["peak_weight"], tail_weight=opts["tail_weight"], verbose=False)
    return EventAnalysis(df, global_events, sub_events, savgol, summary, dt_hours(df), uh_key, opts)


def apply_overrides(global_events: list[Any], sub_events: list[Any],
                    overrides: EventOverrides | None) -> tuple[list[Any], list[Any]]:
    if overrides is None or not overrides.deleted_global_ids:
        return global_events, sub_events
    gone = set(overrides.deleted_global_ids)
    return ([g for g in global_events if int(g.global_id) not in gone],
            [s for s in sub_events if int(s.global_id) not in gone])


__all__ = ["EVENT_OPTIONS", "SEASON_ORDER", "EventAnalysis", "EventOverrides", "apply_overrides", "run_event_analysis"]
