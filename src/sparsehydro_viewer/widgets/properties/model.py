"""Two-column item model over a :class:`PropertyNode` tree (Property | Value)."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QAbstractItemModel, QModelIndex, QPersistentModelIndex, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont

from ... import theme
from .node import MIXED, PropertyNode

MIXED_TEXT = "—"  # em dash, as QPropertyModel shows differing values
NodeRole = Qt.ItemDataRole.UserRole + 1
_NO_INDEX = QModelIndex()  # default parent (read-only, shared)


def format_value(node: PropertyNode, value: Any) -> str:
    if value is MIXED:
        return MIXED_TEXT
    if value is None:
        return ""
    h = node.hints
    if node.value_type == "float":
        text = f"{value:.{h.decimals}f}" if h.decimals is not None else f"{value:.6g}"
    elif node.value_type == "choice":
        text = h.choice_labels.get(value, str(value))
    elif node.value_type == "bool":
        return ""
    elif node.value_type == "datetime":
        text = str(value)[:19].replace("T", " ")
    else:
        text = str(value)
    return f"{text} {h.unit}" if h.unit and node.value_type in ("float", "int") else text


class PropertyModel(QAbstractItemModel):
    """Item model for a property tree.

    The model owns the nodes (PySide does not keep objects passed to
    ``createIndex`` alive).  :attr:`valueChanged` fires after a value was
    written through the model.
    """

    valueChanged = Signal(object)  # PropertyNode

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.root = PropertyNode.group("root")

    # -- content -------------------------------------------------------------

    def set_nodes(self, nodes: list[PropertyNode]) -> None:
        self.beginResetModel()
        self.root = PropertyNode.group("root", nodes)
        self.endResetModel()

    def refresh(self) -> None:
        """Re-read every value (after the objects changed outside the editor)."""
        def walk(parent_index: QModelIndex, node: PropertyNode) -> None:
            n = len(node.children)
            if n:
                self.dataChanged.emit(self.index(0, 1, parent_index), self.index(n - 1, 1, parent_index))
                for r, c in enumerate(node.children):
                    if c.children:
                        walk(self.index(r, 0, parent_index), c)

        walk(QModelIndex(), self.root)

    def node(self, index: QModelIndex) -> PropertyNode:
        return index.internalPointer() if index.isValid() else self.root

    def index_of(self, node: PropertyNode, column: int = 0) -> QModelIndex:
        if node is self.root or node.parent is None:
            return QModelIndex()
        return self.createIndex(node.row(), column, node)

    # -- structure -------------------------------------------------------------

    def index(self, row: int, column: int, parent: QModelIndex | QPersistentModelIndex = _NO_INDEX) -> QModelIndex:
        p = self.node(parent)
        if 0 <= row < len(p.children) and 0 <= column < 2:
            return self.createIndex(row, column, p.children[row])
        return QModelIndex()

    def parent(self, index: QModelIndex | QPersistentModelIndex = _NO_INDEX) -> QModelIndex:  # type: ignore[override]
        if not index.isValid():
            return QModelIndex()
        p = self.node(index).parent
        return self.index_of(p) if p is not None else QModelIndex()

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = _NO_INDEX) -> int:  # noqa: N802
        if parent.isValid() and parent.column() != 0:
            return 0
        return len(self.node(parent).children)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = _NO_INDEX) -> int:  # noqa: N802
        return 2

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # noqa: N802
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return ("Property", "Value")[section]
        return None

    # -- data ---------------------------------------------------------------------

    def flags(self, index: QModelIndex | QPersistentModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        node = self.node(index)
        f = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == 1 and node.editable:
            if node.value_type == "bool":
                f |= Qt.ItemFlag.ItemIsUserCheckable
            else:
                f |= Qt.ItemFlag.ItemIsEditable
        return f

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        node = self.node(index)
        col = index.column()
        if role == NodeRole:
            return node
        if node.is_group:
            if role == Qt.ItemDataRole.DisplayRole and col == 0:
                return node.label
            if role == Qt.ItemDataRole.FontRole:
                f = QFont()
                f.setBold(True)
                return f
            if role == Qt.ItemDataRole.BackgroundRole:
                return QBrush(QColor(theme.current().alt_base))
            if role == Qt.ItemDataRole.ToolTipRole:
                return node.hints.description or None
            return None
        if role == Qt.ItemDataRole.ToolTipRole:
            tip = node.hints.description or node.label
            if node.hints.unit:
                tip += f"  [{node.hints.unit}]"
            return tip
        if col == 0:
            if role == Qt.ItemDataRole.DisplayRole:
                return node.label
            return None
        value = node.value()
        if role == Qt.ItemDataRole.DisplayRole:
            return format_value(node, value)
        if role == Qt.ItemDataRole.EditRole:
            return None if value is MIXED else value
        if role == Qt.ItemDataRole.CheckStateRole and node.value_type == "bool":
            if value is MIXED:
                return Qt.CheckState.PartiallyChecked
            return Qt.CheckState.Checked if value else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.ForegroundRole and (value is MIXED or not node.editable):
            return QBrush(QColor(theme.current().muted))
        if role == Qt.ItemDataRole.FontRole and value is MIXED:
            f = QFont()
            f.setItalic(True)
            return f
        return None

    def setData(self, index: QModelIndex | QPersistentModelIndex, value: Any,  # noqa: N802
                role: int = Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid() or index.column() != 1:
            return False
        node = self.node(index)
        if not node.editable:
            return False
        if role == Qt.ItemDataRole.CheckStateRole and node.value_type == "bool":
            value = Qt.CheckState(value) == Qt.CheckState.Checked
        elif role != Qt.ItemDataRole.EditRole:
            return False
        try:
            node.set_value(value)
        except (ValueError, TypeError, KeyError):
            return False
        self.dataChanged.emit(index, index)
        self.valueChanged.emit(node)
        return True

    def reset_to_default(self, index: QModelIndex) -> bool:
        node = self.node(index)
        if not node.can_reset():
            return False
        return self.setData(self.index_of(node, 1), node.hints.default)


__all__ = ["MIXED_TEXT", "NodeRole", "PropertyModel", "format_value"]
