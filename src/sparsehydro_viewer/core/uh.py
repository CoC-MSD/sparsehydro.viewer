"""Unit hydrograph preview curves.

Finds every unit hydrograph in a built component tree, applies the parent
model's current (prefixed) parameter values to independent copies and returns
unit-area curves in hours with summary statistics.  Copies are used because
composite models keep child parameters under prefixed names (``uh_A``,
``wet_uh2_T``) and only synchronise children during prediction.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

import numpy as np

from .components import Built


@dataclass(frozen=True)
class KernelCurve:
    """One unit hydrograph shape.

    :ivar label: Component label.
    :ivar t_hours: Time at the end of each step, in hours.
    :ivar ordinates: Unit-area ordinates in 1/hr (``sum * dt == 1``).
    :ivar weight: Relative contribution within its group (``R_i`` for RDII
        components, otherwise 1).
    :ivar group: Curves with the same group are combined into one curve.
    """

    label: str
    t_hours: np.ndarray
    ordinates: np.ndarray
    weight: float = 1.0
    group: str = ""

    @property
    def dt(self) -> float:
        return float(self.t_hours[1] - self.t_hours[0]) if len(self.t_hours) > 1 else 1.0

    @property
    def time_to_peak(self) -> float:
        return float(self.t_hours[int(np.argmax(self.ordinates))]) if len(self.ordinates) else float("nan")

    @property
    def peak(self) -> float:
        return float(np.max(self.ordinates)) if len(self.ordinates) else float("nan")

    @property
    def centroid(self) -> float:
        mid = self.t_hours - self.dt / 2.0
        s = float(np.sum(self.ordinates))
        return float(np.sum(mid * self.ordinates) / s) if s > 0 else float("nan")

    def time_to_mass(self, fraction: float) -> float:
        c = np.cumsum(self.ordinates) * self.dt
        i = int(np.searchsorted(c, fraction * c[-1])) if len(c) and c[-1] > 0 else 0
        return float(self.t_hours[min(i, len(self.t_hours) - 1)]) if len(self.t_hours) else float("nan")

    def stats(self) -> dict[str, float]:
        return {
            "time to peak [h]": self.time_to_peak,
            "peak [1/h]": self.peak,
            "centroid [h]": self.centroid,
            "t50 [h]": self.time_to_mass(0.5),
            "t95 [h]": self.time_to_mass(0.95),
        }


def _normalised(kernel: np.ndarray, dt: float) -> np.ndarray:
    k = np.clip(np.asarray(kernel, dtype=float), 0.0, None)
    s = float(k.sum()) * dt
    return k / s if s > 0 else k


def kernel_curves(source: Built | Any, dt_hours: float, max_hours: float | None = None) -> list[KernelCurve]:
    """Unit-area curves for every unit hydrograph in *source* at its current parameters.

    :param source: A :class:`~.components.Built` (initialised) or a bare UH model.
    :param dt_hours: Time step in hours (step-based UH parameters depend on it).
    :param max_hours: Truncate curves after this many hours.
    :returns: One curve per UH; for each RDII group with several UHs a
        ``combined`` curve weighted by ``R_i`` follows its members.
    """
    if not isinstance(source, Built):
        source = Built(source, "Q_pred", uh_paths=[(type(source).__name__, source, "", None)])
    parent = source.model
    names = set(parent.scalar_parameter_names)
    curves: list[KernelCurve] = []
    for label, child, prefix, amp_name in source.uh_paths:
        c = copy.deepcopy(child)
        if not c.is_initialized():
            c.initialize()
        if prefix or c is not parent:
            for name in c.scalar_parameter_names:
                full = f"{prefix}{name}"
                if full in names:
                    c.apply_flat_parameter(name, float(parent.read_flat_parameter(full)))
        k = _normalised(c.get_kernel(dt_hours), dt_hours)
        t = (np.arange(len(k)) + 1.0) * dt_hours
        if max_hours is not None:
            keep = t <= max_hours
            t, k = t[keep], k[keep]
        weight = float(parent.read_flat_parameter(amp_name)) if amp_name and amp_name in names else 1.0
        # UHs of one RDII component share the prefix before "uh{i}_" (possibly empty at the root).
        group = prefix.rsplit("uh", 1)[0] + "|" if amp_name else ""
        curves.append(KernelCurve(label, t, k, weight, group))
    out: list[KernelCurve] = []
    groups: dict[str, list[KernelCurve]] = {}
    for c in curves:
        if c.group:
            groups.setdefault(c.group, []).append(c)
    done: set[str] = set()
    for c in curves:
        out.append(c)
        members = groups.get(c.group, [])
        if c.group and len(members) > 1 and c is members[-1] and c.group not in done:
            done.add(c.group)
            n = max(len(m.ordinates) for m in members)
            total = sum(m.weight for m in members) or 1.0
            comb = np.zeros(n)
            for m in members:
                comb[: len(m.ordinates)] += m.weight / total * m.ordinates
            prefix = c.group.rstrip("|").rstrip("_")
            out.append(KernelCurve(f"{prefix + ': ' if prefix else ''}combined", (np.arange(n) + 1.0) * dt_hours,
                                   comb, 1.0, c.group))
    return out


def display_hours(curves: list[KernelCurve], mass: float = 0.995, minimum: float = 2.0) -> float:
    """Horizon (hours) showing *mass* of every curve."""
    h = minimum
    for c in curves:
        if len(c.ordinates):
            h = max(h, c.time_to_mass(mass))
    return h


__all__ = ["KernelCurve", "display_hours", "kernel_curves"]
