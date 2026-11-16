"""Dataset loading and period handling.

Every dataset is normalised to one frame with columns ``datetime`` (naive,
sorted, unique), ``rain`` (depth per step) and ``stormflow`` (flow), plus an
optional ``temperature_c``.  Catalog entries rename these to whatever their
model reads (see :meth:`ModelEntry.prepare_frame`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

STANDARD_COLUMNS = ("datetime", "rain", "stormflow")

#: Common flow unit conversions to cfs offered in the UI.
FLOW_TO_CFS = {"cfs": 1.0, "MGD": 1.5472286, "gpm": 0.0022280093, "L/s": 0.035314667, "m3/s": 35.314667}


@dataclass
class Period:
    """Inclusive time window; ``None`` bounds are open."""

    start: str | None = None
    end: str | None = None

    def mask(self, t: pd.Series | np.ndarray) -> np.ndarray:
        tt = pd.to_datetime(pd.Series(t))
        m = np.ones(len(tt), dtype=bool)
        if self.start:
            m &= (tt >= pd.Timestamp(self.start)).to_numpy()
        if self.end:
            m &= (tt <= pd.Timestamp(self.end)).to_numpy()
        return m

    @property
    def is_open(self) -> bool:
        return not self.start and not self.end

    def to_dict(self) -> dict[str, Any]:
        return {"start": self.start, "end": self.end}

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> Period:
        d = d or {}
        return cls(d.get("start"), d.get("end"))


@dataclass
class DatasetSpec:
    """Where a dataset comes from and how to read it.

    :ivar name: Display name, unique within a project.
    :ivar kind: ``"csv"`` (one file with all columns) or ``"tsf"`` (separate
        FlowFinity rain and flow files).
    :ivar path: CSV path, or the rain ``.tsf`` path.
    :ivar flow_path: Flow ``.tsf`` path (``kind == "tsf"``).
    :ivar columns: CSV column for each standard name.
    :ivar flow_units: Key of :data:`FLOW_TO_CFS` applied to the flow column.
    :ivar clip_negative_flow: Set negative flows to zero.
    :ivar calibration: Calibration period.
    :ivar validation: Validation period (may be open, meaning "not used").
    :ivar site_iri: Monitoring site the dataset belongs to in the project database.
    :ivar rain_stream: Datastream holding the rainfall series (project database).
    :ivar flow_stream: Datastream holding the observed flow series.
    :ivar temperature_stream: Datastream holding air temperature, if any.

    The source fields (``kind``, ``path``, ``columns``...) record where the data
    came from; once imported the series are read from the project database.
    """

    name: str
    kind: Literal["csv", "tsf"] = "csv"
    path: str = ""
    flow_path: str = ""
    columns: dict[str, str] = field(default_factory=lambda: {c: c for c in STANDARD_COLUMNS})
    flow_units: str = "cfs"
    clip_negative_flow: bool = True
    calibration: Period = field(default_factory=Period)
    validation: Period = field(default_factory=Period)
    site_iri: str | None = None
    rain_stream: str | None = None
    flow_stream: str | None = None
    temperature_stream: str | None = None

    @property
    def stored(self) -> bool:
        """``True`` when the series are in the project database."""
        return bool(self.rain_stream and self.flow_stream)

    def to_dict(self, base: Path | None = None) -> dict[str, Any]:
        def rel(p: str) -> str:
            if not p or base is None:
                return p
            try:
                return str(Path(p).resolve().relative_to(base.resolve()))
            except ValueError:
                return p

        return {
            "name": self.name, "kind": self.kind, "path": rel(self.path), "flow_path": rel(self.flow_path),
            "columns": dict(self.columns), "flow_units": self.flow_units,
            "clip_negative_flow": self.clip_negative_flow,
            "calibration": self.calibration.to_dict(), "validation": self.validation.to_dict(),
            "site_iri": self.site_iri, "rain_stream": self.rain_stream, "flow_stream": self.flow_stream,
            "temperature_stream": self.temperature_stream,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any], base: Path | None = None) -> DatasetSpec:
        def absol(p: str) -> str:
            if not p or base is None or Path(p).is_absolute():
                return p
            return str(base / p)

        return cls(
            name=d["name"], kind=d.get("kind", "csv"), path=absol(d.get("path", "")),
            flow_path=absol(d.get("flow_path", "")),
            columns=dict(d.get("columns", {c: c for c in STANDARD_COLUMNS})),
            flow_units=d.get("flow_units", "cfs"), clip_negative_flow=d.get("clip_negative_flow", True),
            calibration=Period.from_dict(d.get("calibration")), validation=Period.from_dict(d.get("validation")),
            site_iri=d.get("site_iri"), rain_stream=d.get("rain_stream"), flow_stream=d.get("flow_stream"),
            temperature_stream=d.get("temperature_stream"),
        )


def sniff_columns(path: str | Path) -> list[str]:
    """Header of a CSV file."""
    return list(pd.read_csv(path, nrows=0).columns)


def guess_columns(columns: list[str]) -> dict[str, str]:
    """Best-effort mapping of CSV headers to standard names."""
    lower = {c.lower(): c for c in columns}

    def pick(*cands: str) -> str:
        for c in cands:
            for k, orig in lower.items():
                if k == c or k.startswith(c):
                    return orig
        return ""

    return {
        "datetime": pick("datetime", "date_time", "date", "time", "timestamp"),
        "rain": pick("rain", "rainfall", "precip", "p_"),
        "stormflow": pick("stormflow", "storm", "rdii", "flow", "q"),
        "temperature_c": pick("temperature_c", "temperature", "temp", "air_temp"),
    }


def load_dataset(spec: DatasetSpec) -> pd.DataFrame:
    """Read and normalise a dataset.

    :param spec: Dataset description.
    :returns: Frame with ``datetime``, ``rain``, ``stormflow`` (and
        ``temperature_c`` when mapped).
    :raises ValueError: If required columns are missing or no rows overlap.
    """
    if spec.kind == "tsf":
        from sparsehydro.data.utilities import read_tsf

        rain = read_tsf(spec.path).iloc[:, 0].rename("rain")
        flow = read_tsf(spec.flow_path).iloc[:, 0].rename("stormflow")
        df = pd.concat([rain, flow], axis=1, join="inner").reset_index()
        df.columns = ["datetime", "rain", "stormflow"]
    else:
        raw = pd.read_csv(spec.path)
        cols = {std: src for std, src in spec.columns.items() if src}
        missing = [c for c in STANDARD_COLUMNS if c not in cols or cols[c] not in raw.columns]
        if missing:
            raise ValueError(f"{spec.name}: no column mapped for {missing}; file has {list(raw.columns)}")
        df = pd.DataFrame({std: raw[src] for std, src in cols.items() if src in raw.columns})

    df["datetime"] = pd.to_datetime(df["datetime"])
    if getattr(df["datetime"].dt, "tz", None) is not None:
        df["datetime"] = df["datetime"].dt.tz_localize(None)
    # One resolution everywhere (pandas 3 parses text at microseconds; the project database stores ns).
    df["datetime"] = df["datetime"].astype("datetime64[ns]")
    for c in df.columns:
        if c != "datetime":
            df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    df["stormflow"] = df["stormflow"] * FLOW_TO_CFS.get(spec.flow_units, 1.0)
    if spec.clip_negative_flow:
        df["stormflow"] = df["stormflow"].clip(lower=0.0)
    df["rain"] = df["rain"].fillna(0.0).clip(lower=0.0)
    df = df.dropna(subset=["datetime"]).drop_duplicates("datetime").sort_values("datetime").reset_index(drop=True)
    if df.empty:
        raise ValueError(f"{spec.name}: no rows after reading and aligning")
    return df


@dataclass(frozen=True)
class DatasetSummary:
    rows: int
    start: pd.Timestamp
    end: pd.Timestamp
    dt_minutes: float
    irregular_steps: int
    total_rain: float
    missing_flow: int
    peak_flow: float


def summarize(df: pd.DataFrame) -> DatasetSummary:
    dts = df["datetime"].diff().dt.total_seconds().div(60.0).dropna()
    dt = float(dts.median()) if len(dts) else float("nan")
    return DatasetSummary(
        rows=len(df), start=df["datetime"].iloc[0], end=df["datetime"].iloc[-1], dt_minutes=dt,
        irregular_steps=int((~np.isclose(dts, dt)).sum()) if len(dts) else 0,
        total_rain=float(df["rain"].sum()), missing_flow=int(df["stormflow"].isna().sum()),
        peak_flow=float(np.nanmax(df["stormflow"].to_numpy())) if len(df) else float("nan"),
    )


def dt_hours(df: pd.DataFrame) -> float:
    """Median time step in hours (5 minutes if undeterminable)."""
    if len(df) < 2:
        return 1.0 / 12.0
    return float(df["datetime"].diff().median().total_seconds() / 3600.0)


def slice_period(df: pd.DataFrame, period: Period) -> pd.DataFrame:
    if period.is_open:
        return df
    return df.loc[period.mask(df["datetime"])].reset_index(drop=True)


def epoch_seconds(t: pd.Series | np.ndarray) -> np.ndarray:
    """Datetimes as float seconds since the epoch (pyqtgraph's DateAxisItem convention, naive = UTC)."""
    return pd.to_datetime(pd.Series(t)).to_numpy(dtype="datetime64[ns]").astype("int64") / 1e9


__all__ = [
    "FLOW_TO_CFS",
    "STANDARD_COLUMNS",
    "DatasetSpec",
    "DatasetSummary",
    "Period",
    "dt_hours",
    "epoch_seconds",
    "guess_columns",
    "load_dataset",
    "slice_period",
    "sniff_columns",
    "summarize",
]
