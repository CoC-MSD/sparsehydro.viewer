"""Process-oriented model design.

Users build a model by adding hydrological processes, not by assembling a
component tree:

1. **Rainfall losses** - none, initial abstraction (optionally with
   degree-day snowmelt) or a drained tank;
2. **Runoff routing** - one or more unit hydrographs of any type;
3. **Other flow components** - sanitary (dry-weather) pattern; groundwater
   infiltration once the library provides it.

:func:`to_tree` turns a :class:`ProcessDesign` into the component tree
(:mod:`.components`), :func:`from_tree` recognises trees that came from a
design, and :func:`renames` maps parameter names between two designs so
values the user has tuned follow their process when the design changes.

Structure produced (aliases are fixed so parameter names are predictable):

=========================  ==============================================
design                     tree / parameter prefixes
=========================  ==============================================
losses, no sanitary        ``rdii``: losses ``""``, UH *i* ``uh{i}_``, ``R_{i}``
losses + sanitary          ``sum[wet=rdii, san]``: ``wet_``, ``wet_uh{i}_``
no losses, one UH          the UH itself: ``""`` (amplitude ``A``)
no losses, several UHs     ``sum[uh1, uh2, ...]``: ``uh{i}_``
no losses + sanitary       ``sum[wet=..., san]``: ``wet_`` / ``wet_uh{i}_``
=========================  ==============================================
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from .components import COMPONENTS, ComponentSpec, new_component

LOSS_KEYS: tuple[str, ...] = ("initial-abstraction", "tank-constant", "tank-linear", "tank-sqrt")
ROUTING_KEYS: tuple[str, ...] = (
    "rtk-triangle", "triangle-uh", "gamma-uh", "nash-uh", "gamma-delay-uh", "peak-tail-uh", "rectangle-uh",
    "decay-uh",
)
#: Unit hydrographs that route rainfall *excess* and therefore need a losses process.
NEEDS_LOSSES: frozenset[str] = frozenset({"rtk-triangle"})

#: Processes the library does not provide yet (enabled when the viewer moves to the refactored library).
UNAVAILABLE = {
    "groundwater": "Groundwater infiltration needs sparsehydro's soil-groundwater store, which arrives when the "
                   "viewer moves to the refactored library.",
}


@dataclass
class ProcessDesign:
    """What the user has put together.

    :ivar losses: Key in :data:`LOSS_KEYS`, or ``None`` (all rain becomes runoff).
    :ivar snow: Degree-day snowmelt (initial abstraction only).
    :ivar routing: Unit hydrograph keys, in order (at least one).
    :ivar sanitary: Add a dry-weather (sanitary) pattern.
    :ivar sanitary_options: ``hour``, ``day_of_week``, ``month`` flags.
    :ivar loss_options: Extra options of the losses component (e.g. tank sub-steps).
    """

    losses: str | None = "initial-abstraction"
    snow: bool = False
    routing: list[str] = field(default_factory=lambda: ["rtk-triangle"])
    sanitary: bool = False
    sanitary_options: dict[str, bool] = field(default_factory=lambda: {"hour": True, "day_of_week": True,
                                                                       "month": True})
    loss_options: dict[str, Any] = field(default_factory=dict)

    def copy(self) -> ProcessDesign:
        return copy.deepcopy(self)

    def problems(self) -> list[str]:
        """Reasons the design cannot be built (empty when it is valid)."""
        out = []
        if not self.routing:
            out.append("Add at least one unit hydrograph.")
        if self.losses is None and any(k in NEEDS_LOSSES for k in self.routing):
            names = ", ".join(sorted({COMPONENTS[k].label for k in self.routing if k in NEEDS_LOSSES}))
            out.append(f"{names} route rainfall excess: choose a rainfall-losses process, or use another "
                       "unit hydrograph type.")
        return out

    def describe(self) -> str:
        parts = []
        if self.losses:
            parts.append(_SHORT.get(self.losses, self.losses) + (" + snow" if self.snow else ""))
        parts.append(" + ".join(_SHORT.get(k, k) for k in self.routing))
        text = " → ".join(parts)
        if self.sanitary:
            text += "  + sanitary"
        return text


_SHORT = {"initial-abstraction": "IA", "tank-constant": "tank", "tank-linear": "tank (linear)",
          "tank-sqrt": "tank (sqrt)", "rtk-triangle": "RTK", "triangle-uh": "triangle", "gamma-uh": "gamma",
          "nash-uh": "Nash", "gamma-delay-uh": "delayed gamma", "peak-tail-uh": "peak+tail",
          "rectangle-uh": "rectangle", "decay-uh": "decay"}


# ---------------------------------------------------------------------------
# design -> tree
# ---------------------------------------------------------------------------


def _losses(design: ProcessDesign) -> ComponentSpec:
    node = new_component(design.losses)  # type: ignore[arg-type]
    if design.losses == "initial-abstraction":
        node.options["snow"] = bool(design.snow)
    for k, v in design.loss_options.items():
        if k in {o.name for o in COMPONENTS[design.losses].options}:  # type: ignore[index]
            node.options[k] = v
    return node


def _routing(design: ProcessDesign) -> ComponentSpec:
    if design.losses is not None:
        node = new_component("rdii")
        node.slots["abstraction"] = _losses(design)
        node.slots["uhs"] = [new_component(k) for k in design.routing]
        return node
    if len(design.routing) == 1:
        return new_component(design.routing[0])
    node = new_component("sum")
    node.slots["terms"] = []
    for i, k in enumerate(design.routing, start=1):
        term = new_component(k)
        term.alias = f"uh{i}"
        node.slots["terms"].append(term)
    return node


def to_tree(design: ProcessDesign) -> ComponentSpec:
    """Component tree for *design* (raises :class:`ValueError` when :meth:`ProcessDesign.problems`)."""
    problems = design.problems()
    if problems:
        raise ValueError(" ".join(problems))
    routing = _routing(design)
    if not design.sanitary:
        return routing
    root = new_component("sum")
    routing.alias = "wet"
    san = new_component("sanitary")
    san.options.update(design.sanitary_options)
    san.alias = "san"
    root.slots["terms"] = [routing, san]
    return root


# ---------------------------------------------------------------------------
# tree -> design
# ---------------------------------------------------------------------------


def from_tree(root: ComponentSpec) -> ProcessDesign | None:
    """The design that produced *root*, or ``None`` when the tree was built in the advanced editor."""
    sanitary = None
    routing = root
    if root.type == "sum":
        terms = root.slots.get("terms", [])
        aliases = [t.alias for t in terms]
        if len(terms) == 2 and aliases == ["wet", "san"] and terms[1].type == "sanitary":
            routing, sanitary = terms
    design = ProcessDesign(losses=None, snow=False, routing=[], sanitary=sanitary is not None)
    if sanitary is not None:
        design.sanitary_options = {k: bool(sanitary.options.get(k, True)) for k in ("hour", "day_of_week", "month")}
    if routing.type == "rdii":
        losses = routing.slots["abstraction"]
        if losses.type not in LOSS_KEYS:
            return None
        design.losses = losses.type
        design.snow = bool(losses.options.get("snow", False))
        design.loss_options = {k: v for k, v in losses.options.items() if k != "snow"}
        design.routing = [u.type for u in routing.slots["uhs"]]
    elif routing.type == "sum":
        terms = routing.slots.get("terms", [])
        if [t.alias for t in terms] != [f"uh{i}" for i in range(1, len(terms) + 1)] or len(terms) < 2:
            return None
        if any(t.type not in ROUTING_KEYS or t.slots for t in terms):
            return None
        design.routing = [t.type for t in terms]
    elif routing.type in ROUTING_KEYS:
        design.routing = [routing.type]
    else:
        return None
    if design.problems() or to_tree(design).to_dict() != root.to_dict():
        return None
    return design


# ---------------------------------------------------------------------------
# parameter renames between designs
# ---------------------------------------------------------------------------


def prefixes(design: ProcessDesign) -> dict[str, str]:
    """Flat-name prefix of every process (``losses``, ``uh:<i>``, ``sanitary``) in the built model."""
    out: dict[str, str] = {}
    wet = "wet_" if design.sanitary else ""
    if design.losses is not None:
        out["losses"] = wet
        out["area"] = f"{wet}area_acres"
        for i in range(len(design.routing)):
            out[f"uh:{i}"] = f"{wet}uh{i + 1}_"
            out[f"R:{i}"] = f"{wet}R_{i + 1}"
    elif len(design.routing) == 1:
        out["uh:0"] = wet
    else:
        for i in range(len(design.routing)):
            out[f"uh:{i}"] = f"{wet}uh{i + 1}_"
    if design.sanitary:
        out["sanitary"] = "san_"
    return out


def renames(old: ProcessDesign, new: ProcessDesign, uh_map: dict[int, int] | None = None) -> dict[str, str]:
    """Parameter renames from *old* to *new* (see :func:`~sparsehydro_viewer.widgets.model_composer.apply_renames`).

    :param uh_map: Old unit hydrograph index -> new index (default: same index); entries for
        hydrographs whose type changed are dropped, since their parameters differ.
    """
    a, b = prefixes(old), prefixes(new)
    mapping = uh_map if uh_map is not None else {i: i for i in range(min(len(old.routing), len(new.routing)))}
    out: dict[str, str] = {}
    for i, j in mapping.items():
        if i >= len(old.routing) or j >= len(new.routing) or old.routing[i] != new.routing[j]:
            continue
        if f"uh:{i}" in a and f"uh:{j}" in b:
            out[a[f"uh:{i}"]] = b[f"uh:{j}"]
        if f"R:{i}" in a and f"R:{j}" in b:
            out[a[f"R:{i}"]] = b[f"R:{j}"]
    if old.losses is not None and new.losses is not None:
        out[a["area"]] = b["area"]  # the contributing area survives a change of losses type
        if old.losses == new.losses:
            out[a["losses"]] = b["losses"]  # prefix of the losses process' own parameters
    if old.sanitary and new.sanitary:
        out[a["sanitary"]] = b["sanitary"]
    # A single direct UH sits at the root (prefix ""), so a rename from "" would capture everything;
    # it is only correct when that UH is the only process carried over.
    if "" in out and len(out) > 1 and old.losses is None:
        out.pop("")
    return out


__all__ = ["LOSS_KEYS", "NEEDS_LOSSES", "ROUTING_KEYS", "UNAVAILABLE", "ProcessDesign", "from_tree", "prefixes",
           "renames", "to_tree"]
