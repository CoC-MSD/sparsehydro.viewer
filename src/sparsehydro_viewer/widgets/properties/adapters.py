"""Build property trees for the application's objects.

Adapters never write to the store themselves: they call back into the
session (``update_node`` / ``set_attribute``), which writes, marks the
project dirty and notifies every view.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from ...core.geometry import parse_point, point_wkt
from ...core.options import OptionSpec
from ...core.store import ProjectStore
from .node import Hints, PropertyNode

KIND_LABELS = {"monitoring_site": "Monitoring site", "sensor": "Sensor", "zone": "Zone"}


def from_option_specs(specs: Sequence[OptionSpec], values: dict[str, Any],
                      on_change: Callable[[dict[str, Any]], None], *,
                      choice_labels: dict[Any, str] | None = None) -> list[PropertyNode]:
    """Nodes for constructor options (models, solvers, objectives, event settings)."""
    state = dict(values)
    nodes = []
    for s in specs:
        def getter(name: str = s.name, default: Any = s.default) -> Any:
            return state.get(name, default)

        def setter(v: Any, name: str = s.name) -> None:
            state[name] = v
            on_change(dict(state))

        nodes.append(PropertyNode(s.name, s.kind, getter, setter, Hints(
            label=s.display_label, description=s.doc, minimum=s.minimum, maximum=s.maximum, default=s.default,
            choices=tuple(s.choices), choice_labels=dict(choice_labels or {}),
            decimals=4 if s.kind == "float" else None)))
    return nodes


def node_properties(store: ProjectStore, iris: Sequence[str], *,
                    update_node: Callable[..., None], set_attribute: Callable[[str, str, Any], None]) -> list[PropertyNode]:
    """Properties of one or several nodes (sites, sensors, zones).

    With several nodes, values that differ show as an em dash and an edit applies to all of them;
    location is only editable for a single node.
    """
    nodes = [n for iri in iris if (n := store.node(iri)) is not None]
    if not nodes:
        return []
    single = len(nodes) == 1

    def field_getter(attr: str) -> Callable[[], Any]:
        return lambda: [getattr(store.node(n.iri), attr) for n in nodes]

    def field_setter(attr: str) -> Callable[[Any], None]:
        def set_(v: Any) -> None:
            for n in nodes:
                update_node(n.iri, **{attr: v})
        return set_

    general = PropertyNode.group("General", [
        PropertyNode("kind", "str", lambda: [KIND_LABELS[n.table] + (f" ({n.extra['sensor_kind']})"
                                                                    if n.extra.get("sensor_kind") else "")
                                             for n in nodes],
                     hints=Hints(label="Type", readonly=True)),
        PropertyNode("label", "str", field_getter("label"), field_setter("label"), Hints(label="Name")),
        PropertyNode("description", "text", field_getter("description"), field_setter("description"),
                     Hints(label="Description")),
        PropertyNode("source_system", "str", field_getter("source_system"), hints=Hints(
            label="Source", readonly=True, description="Where the node and its data came from")),
        PropertyNode("iri", "str", lambda: [n.iri for n in nodes], hints=Hints(
            label="Identifier", readonly=True, description="Ontology IRI (wsys namespace)")),
    ])

    def coord(i: int) -> Callable[[], Any]:
        def get() -> Any:
            vals = []
            for n in nodes:
                p = parse_point(store.node(n.iri).geometry)  # type: ignore[union-attr]
                vals.append(None if p is None else p[i])
            return vals
        return get

    def coord_setter(i: int) -> Callable[[Any], None]:
        def set_(v: Any) -> None:
            n = nodes[0]
            p = parse_point(store.node(n.iri).geometry) or (0.0, 0.0)  # type: ignore[union-attr]
            lon, lat = (float(v), p[1]) if i == 0 else (p[0], float(v))
            update_node(n.iri, geometry=point_wkt(lon, lat))
        return set_

    location = PropertyNode.group("Location", [
        PropertyNode("longitude", "float", coord(0), coord_setter(0) if single else None,
                     Hints(label="Longitude", unit="°", minimum=-180, maximum=180, decimals=6,
                           description="WGS 84 (EPSG:4326)")),
        PropertyNode("latitude", "float", coord(1), coord_setter(1) if single else None,
                     Hints(label="Latitude", unit="°", minimum=-90, maximum=90, decimals=6,
                           description="WGS 84 (EPSG:4326)")),
    ], description="Stored as WKT geometry; polygons (zones) are edited on the map.")
    groups = [general, location]

    by_category: dict[str, list[PropertyNode]] = {}
    for d in store.attribute_definitions():
        if d.applies_to and not all(n.class_iri in d.applies_to for n in nodes):
            continue

        def get(key: str = d.key) -> Any:
            return [store.attributes(n.iri).get(key) for n in nodes]

        def set_(v: Any, key: str = d.key, vtype: str = d.value_type) -> None:
            value = None if (vtype in ("str", "text") and v == "") else v
            for n in nodes:
                set_attribute(n.iri, key, value)

        vtype = {"str": "str", "float": "float", "int": "int", "bool": "bool", "choice": "choice",
                 "datetime": "datetime"}[d.value_type]
        by_category.setdefault(d.category, []).append(PropertyNode(d.key, vtype, get, set_, Hints(
            label=d.label, unit=d.unit, minimum=d.minimum, maximum=d.maximum, decimals=d.decimals,
            choices=d.choices, description=d.description + ("" if d.ontology_slot else "  (viewer attribute)"))))
    for cat in sorted(by_category):
        groups.append(PropertyNode.group(cat, by_category[cat]))
    return groups


__all__ = ["KIND_LABELS", "from_option_specs", "node_properties"]
