"""Ready-to-use property editor view."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QMenu, QTreeView, QWidget

from .delegate import PropertyDelegate
from .model import PropertyModel
from .node import PropertyNode


class PropertyEditor(QTreeView):
    """Tree view + :class:`PropertyModel` + :class:`PropertyDelegate`.

    Right-click a property to reset it to its default.  :attr:`valueChanged`
    forwards the model's signal.
    """

    valueChanged = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.property_model = PropertyModel(self)
        self.setModel(self.property_model)
        self.setItemDelegate(PropertyDelegate(self))
        self.setAlternatingRowColors(True)
        self.setUniformRowHeights(True)
        self.setRootIsDecorated(True)
        self.setEditTriggers(QAbstractItemView.EditTrigger.AllEditTriggers)
        self.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.header().setStretchLastSection(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.property_model.valueChanged.connect(self.valueChanged)

    def set_nodes(self, nodes: list[PropertyNode]) -> None:
        self.property_model.set_nodes(nodes)
        self.expandAll()

    def refresh(self) -> None:
        self.property_model.refresh()

    def _menu(self, pos) -> None:
        index = self.indexAt(pos)
        if not index.isValid():
            return
        node = self.property_model.node(index)
        menu = QMenu(self)
        reset = menu.addAction("Reset to default")
        reset.setEnabled(node.can_reset())
        if node.can_reset():
            reset.setToolTip(f"Default: {node.hints.default}")
        act = menu.exec(self.viewport().mapToGlobal(pos))
        if act is reset:
            self.property_model.reset_to_default(self.property_model.index_of(node, 1) or QModelIndex())


__all__ = ["PropertyEditor"]
