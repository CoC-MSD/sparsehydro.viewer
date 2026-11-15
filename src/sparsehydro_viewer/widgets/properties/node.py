"""Property tree nodes (plain Python; the model owns them).

Follows QPropertyModel's design (HydroCouple/QPropertyModel, dev branch): a
tree of items, one per property, each knowing how to read and write its value,
grouped under category rows.  Unlike QPropertyModel, metadata (units, limits,
decimals, choices, descriptions, defaults) is explicit, and a node may edit
several objects at once (its getter returns one value per object).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

VALUE_TYPES = ("float", "int", "str", "text", "bool", "choice", "datetime", "file", "group")

#: Marker for "objects have different values" (multi-object editing).
MIXED = object()


@dataclass
class Hints:
    """Editor metadata.

    :ivar editor: Optional editor override, e.g. ``"text"`` (multi-line).
    :ivar default: Value restored by "Reset to default" (``None``: no reset).
    """

    label: str = ""
    unit: str = ""
    minimum: float | None = None
    maximum: float | None = None
    decimals: int | None = None
    choices: tuple[Any, ...] = ()
    choice_labels: dict[Any, str] = field(default_factory=dict)
    description: str = ""
    readonly: bool = False
    default: Any = None
    file_filter: str = ""


class PropertyNode:
    """One row: a property (``value_type`` other than ``group``) or a category heading.

    :param getter: Returns the value, or a list of values (one per edited
        object) when the node edits several objects.
    :param setter: Applies a new value (to every edited object); ``None``
        makes the node read-only.
    """

    def __init__(self, name: str, value_type: str, getter: Callable[[], Any] | None = None,
                 setter: Callable[[Any], None] | None = None, hints: Hints | None = None,
                 children: list[PropertyNode] | None = None) -> None:
        if value_type not in VALUE_TYPES:
            raise ValueError(f"unknown value type {value_type!r}")
        self.name = name
        self.value_type = value_type
        self.getter = getter
        self.setter = setter
        self.hints = hints or Hints()
        self.parent: PropertyNode | None = None
        self.children: list[PropertyNode] = []
        for c in children or []:
            self.add(c)

    @classmethod
    def group(cls, name: str, children: list[PropertyNode] | None = None, description: str = "") -> PropertyNode:
        return cls(name, "group", hints=Hints(description=description), children=children)

    def add(self, child: PropertyNode) -> PropertyNode:
        child.parent = self
        self.children.append(child)
        return child

    @property
    def label(self) -> str:
        return self.hints.label or self.name

    @property
    def is_group(self) -> bool:
        return self.value_type == "group"

    @property
    def editable(self) -> bool:
        return not self.is_group and self.setter is not None and not self.hints.readonly

    def row(self) -> int:
        return self.parent.children.index(self) if self.parent else 0

    def value(self) -> Any:
        """The value, or :data:`MIXED` when edited objects disagree."""
        if self.getter is None:
            return None
        v = self.getter()
        if isinstance(v, list) and self.value_type != "group":
            if not v:
                return None
            first = v[0]
            return first if all(_equal(first, x) for x in v[1:]) else MIXED
        return v

    def set_value(self, value: Any) -> None:
        if not self.editable:
            raise PermissionError(f"{self.name} is read-only")
        self.setter(_coerce(self.value_type, value))  # type: ignore[misc]

    def can_reset(self) -> bool:
        return self.editable and self.hints.default is not None

    def find(self, name: str) -> PropertyNode | None:
        if self.name == name:
            return self
        for c in self.children:
            hit = c.find(name)
            if hit is not None:
                return hit
        return None


def _equal(a: Any, b: Any) -> bool:
    try:
        return bool(a == b)
    except Exception:  # e.g. arrays
        return False


def _coerce(value_type: str, value: Any) -> Any:
    if value is None:
        return None
    if value_type == "float":
        return float(value)
    if value_type == "int":
        return int(value)
    if value_type == "bool":
        return bool(value)
    if value_type in ("str", "text", "file"):
        return str(value)
    return value


__all__ = ["MIXED", "VALUE_TYPES", "Hints", "PropertyNode"]
