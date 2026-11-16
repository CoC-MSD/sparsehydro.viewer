"""MSDGC calibration assessment of a model on a dataset.

Events are detected on the observed record with sparsehydro's MSDGC detector
(:func:`sparsehydro.studies.msdgc.detector.find_events`, the tool's
``findEvents``); the model is simulated over the chosen period; the result is
graded by :func:`sparsehydro.studies.msdgc.scorecard.assess_calibration`
(Modeling Guidelines Rev 5.8, Volume II Sections 6.4 and 7.1). Site
attributes supply what the guidelines take from the monitor: the average dry
weather flow ODWF-A, the sewer system type and, as a fallback, a capacity
flow.

Viewer datasets carry storm flow (base flow removed), so the storm-volume
approach shifts each event to a zero mean over the 24 h before it; the result
says so in its warnings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .catalog import ModelSpec
from .data import Period, slice_period
from .options import OptionSpec

#: Choices shown in the settings form.
APPROACHES = {"storm": "Storm volume", "total": "Total volume"}
ZONE_PRESETS = {"tool": "MSDGC tool v5.0.5 (treatment ≤ 24 h)", "guidelines": "Guidelines Rev 5.8 (no cap)"}
PERIODS = {"calibration": "Calibration period", "validation": "Validation period", "whole": "Whole record"}

ASSESS_OPTIONS: tuple[OptionSpec, ...] = (
    OptionSpec("period", "choice", "calibration", label="Period", choices=tuple(PERIODS),
               doc="Part of the record the model is assessed on."),
    OptionSpec("approach", "choice", "storm", label="Volume approach", choices=tuple(APPROACHES),
               doc="Storm volume (Guidelines 6.4.1, the default) or total volume (6.4.2, for poor base-flow data)."),
    OptionSpec("zones", "choice", "tool", label="Zone windows", choices=tuple(ZONE_PRESETS),
               doc="The assessment tool caps the treatment window at 24 h; the guidelines' Table 6-1 does not."),
    OptionSpec("interevent_hours", "float", 6.0, label="Inter-event period [h]", minimum=0.5, maximum=96.0,
               doc="Dry period that separates two events (Guidelines 6.2: 6 h for most areas)."),
    OptionSpec("min_rain_in", "float", 0.2, label="Minimum event rain [in]", minimum=0.0, maximum=10.0,
               doc="Events with less rain are not detected."),
    OptionSpec("min_duration_hours", "float", 3.0, label="Minimum duration [h]", minimum=0.0, maximum=240.0,
               doc="Shorter events are not detected."),
    OptionSpec("threshold_pct", "float", 5.0, label="Start/end threshold [%]", minimum=0.0, maximum=100.0,
               doc="Storm flow, as a percent of the event peak, that marks an event's start and end."),
)


@dataclass
class AssessmentRun:
    """What the Assess page shows: the graded result and the series behind it."""

    result: Any  # sparsehydro.studies.msdgc.scorecard.MSDGCScorecardResult
    datetime: np.ndarray
    observed: np.ndarray
    simulated: np.ndarray
    rain: np.ndarray
    events: pd.DataFrame
    source: str
    period: str
    notes: list[str] = field(default_factory=list)


def detect_events(frame: pd.DataFrame, options: dict[str, Any]) -> pd.DataFrame:
    """MSDGC events on *frame* (``datetime``, ``rain``, ``stormflow``), indices relative to it."""
    from sparsehydro.studies.msdgc.detector import find_events, msdgc_events_to_dataframe

    events = find_events(frame.reset_index(drop=True), threshold_pct=float(options["threshold_pct"]),
                         interevent_hours=float(options["interevent_hours"]),
                         min_rain_in=float(options["min_rain_in"]),
                         min_duration_hours=float(options["min_duration_hours"]))
    return msdgc_events_to_dataframe(events)


def site_inputs(attributes: dict[str, Any], approach: str) -> tuple[float | None, str, list[str]]:
    """ODWF-A, sewer system and notes from site attributes (capacity flow as a fallback for Qc1)."""
    from sparsehydro.studies.msdgc.scorecard import MSDGCCriteria

    notes: list[str] = []
    system = attributes.get("shv:sewer_system") or "sanitary"
    if "shv:sewer_system" not in attributes:
        notes.append("Sewer system not set on the site: assumed sanitary.")
    odwf = attributes.get("shv:odwf_a")
    capacity = attributes.get("shv:capacity_flow")
    if (odwf is None or not odwf > 0) and capacity and capacity > 0:
        odwf = float(capacity) / MSDGCCriteria().qcritical_factor(approach, system)
        notes.append(f"ODWF-A not set on the site: Qc1 taken from its capacity flow ({capacity:g} cfs).")
    return (float(odwf) if odwf and odwf > 0 else None), system, notes


def run_assessment(spec: ModelSpec, values: dict[str, float], frame: pd.DataFrame, dataset, attributes: dict,
                   options: dict[str, Any], objectives, source: str = "working model") -> AssessmentRun:
    """Simulate *spec* with *values* over the chosen period and grade it."""
    from sparsehydro.studies.msdgc.scorecard import GUIDELINE_ZONES, TOOL_ZONES, assess_calibration

    from .evaluation import Evaluator

    period_key = options.get("period", "calibration")
    period = {"calibration": dataset.calibration, "validation": dataset.validation}.get(period_key, Period())
    if period_key == "validation" and dataset.validation.is_open:
        raise ValueError("The dataset has no validation period; set one on the Sites page.")
    part = slice_period(frame, period).reset_index(drop=True)
    ev = Evaluator(spec, part, objectives, Period())
    sim = ev.evaluate(values).predicted
    events = detect_events(part, options)
    approach = options.get("approach", "storm")
    odwf, system, notes = site_inputs(attributes, approach)
    result = assess_calibration(
        ev.observed, sim, ev.datetime, events, ev.dt_hours, approach=approach, system=system, odwf_a=odwf,
        zones=GUIDELINE_ZONES if options.get("zones") == "guidelines" else TOOL_ZONES)
    result.warnings[:0] = notes
    return AssessmentRun(result, ev.datetime, ev.observed, sim, ev.rain, events, source, PERIODS[period_key], notes)


__all__ = ["APPROACHES", "ASSESS_OPTIONS", "PERIODS", "ZONE_PRESETS", "AssessmentRun", "detect_events",
           "run_assessment", "site_inputs"]
