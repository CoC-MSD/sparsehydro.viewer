"""Model traces: the hydrograph's components and the model's internal states.

sparsehydro models report a *trace* besides their outputs
(:meth:`IModel.predict_trace`): additive components of an output (each unit
hydrograph of an RDII model, each part of a mixture, each term of a sum) and
internal states and fluxes (remaining abstraction, tank storage, soil and
groundwater stores, snowpack, melt...), each described by a ``FieldRecord``
with a ``role``. This module turns that metadata into what the views need:
readable labels, a grouping for the states tree, and the expansion of the
predicted flow into its individual hydrographs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class TraceField:
    """One traced series.

    :ivar name: Address in the model, e.g. ``"wet.rdii_component_2"`` or ``"ia.ia_available"``.
    :ivar role: ``"component"``, ``"state"`` or ``"flux"``.
    :ivar component_of: For components: the series it adds up to.
    """

    name: str
    role: str
    component_of: str = ""
    units: str = ""
    description: str = ""

    @property
    def group(self) -> str:
        """Address of the model part it belongs to (``""`` for the root)."""
        return self.name.rsplit(".", 1)[0] if "." in self.name else ""

    @property
    def leaf(self) -> str:
        return self.name.rsplit(".", 1)[-1]

    @property
    def label(self) -> str:
        """Short readable label, e.g. ``"wet › UH 2 (GammaUH)"`` or ``"ia › remaining abstraction"``."""
        parts = [p for p in self.group.split(".") if p]
        return " › ".join(parts + [leaf_label(self.leaf, self.description)])


_LEAF_LABELS = {
    "ia_available": "remaining abstraction", "swe": "snowpack (SWE)", "snowfall": "snowfall", "melt": "melt",
    "tank_storage": "tank storage", "tank_gain": "tank gain", "S_in": "soil store", "G_in": "deep store",
    "SWE_in": "snowpack (SWE)", "p_excess_in": "rainfall excess", "p_excess_mm": "rainfall excess",
    "recharge_in": "recharge", "et_in": "evapotranspiration", "gwi_in": "groundwater infiltration",
    "gwi_cfs": "groundwater infiltration flow", "melt_in": "melt", "snowfall_in": "snowfall",
    "Q_pred": "flow", "rdii_cfs": "RDII flow",
}


def leaf_label(leaf: str, description: str = "") -> str:
    m = re.fullmatch(r"rdii_component_(\d+)", leaf)
    if m:
        kind = re.search(r"\(([^)]+)\)\s*$", description)
        return f"UH {m.group(1)}" + (f" ({kind.group(1)})" if kind else "")
    if leaf.endswith("_contribution"):
        return leaf[: -len("_contribution")]
    if leaf.endswith("_Q_pred"):  # a part of a mixture / peak-tail UH
        return f"{leaf[: -len('_Q_pred')]} part"
    return _LEAF_LABELS.get(leaf, leaf.replace("_", " "))


def trace_fields(model) -> list[TraceField]:
    """The model's trace fields as :class:`TraceField` (empty for a library without traces)."""
    fields = getattr(model, "trace_fields", None) or []
    return [TraceField(f.name, f.role, f.component_of, f.units, f.description) for f in fields]


def flow_parts(fields: list[TraceField], arrays: dict[str, np.ndarray], output: str) -> list[tuple[str, np.ndarray]]:
    """The individual hydrographs that add up to *output*, as ``(field name, series)``.

    Components are expanded recursively to their leaves: a sum into its
    terms, an RDII term into its unit hydrographs, a mixture into its parts.
    An ensemble term (``alias_contribution``, the weighted child output) is
    expanded into its child's components scaled by the term's weight, so the
    returned series still add up to *output*.
    """
    by_owner: dict[str, list[TraceField]] = {}
    names = {f.name: f for f in fields}
    for f in fields:
        if f.role == "component" and f.component_of:
            by_owner.setdefault(f.component_of, []).append(f)

    def expand(name: str, scale: float, depth: int) -> list[tuple[str, np.ndarray]]:
        if depth > 20 or name not in arrays:
            return []
        subs = by_owner.get(name, [])
        if subs:
            out = []
            for s in subs:
                out += expand(s.name, scale, depth + 1)
            return out
        if name.endswith("_contribution"):
            base = name[: -len("_contribution")]
            child = next((o for o in by_owner if o.startswith(base + ".") and o.count(".") == base.count(".") + 1
                          and o in arrays), None)
            if child is not None:
                c, y = np.asarray(arrays[name], float), np.asarray(arrays[child], float)
                denom = float(np.dot(y, y))
                w = float(np.dot(c, y)) / denom if denom > 0 else 0.0
                return expand(child, scale * w, depth + 1)
        return [(name, scale * np.asarray(arrays[name], float))] if name in names else []

    if output not in by_owner and output in arrays:
        # The output may alias a child's output (e.g. Q_pred = uh.Q_pred); its parts hang off the child.
        target = np.asarray(arrays[output], float)
        alias = next((o for o in by_owner if o.rsplit(".", 1)[-1] == output and o in arrays
                      and np.array_equal(np.asarray(arrays[o], float), target)), None)
        if alias is None:
            return []
        output = alias
    return expand(output, 1.0, 0) if output in by_owner else []


def state_fields(fields: list[TraceField]) -> list[TraceField]:
    """States and fluxes (what the states panel lists), in model order."""
    return [f for f in fields if f.role in ("state", "flux")]


__all__ = ["TraceField", "flow_parts", "leaf_label", "state_fields", "trace_fields"]
