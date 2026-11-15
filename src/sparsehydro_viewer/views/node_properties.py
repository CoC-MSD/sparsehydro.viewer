"""Property panel for project-database nodes, and the "add attribute" dialog."""

from __future__ import annotations

import re

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.store import AttributeDefinition
from ..widgets.properties import PropertyEditor, node_properties
from .context import AppContext

VALUE_TYPES = (("float", "Number"), ("int", "Whole number"), ("str", "Text"), ("bool", "Yes / no"),
               ("choice", "Choice from a list"), ("datetime", "Date and time"))


class AddAttributeDialog(QDialog):
    """Define a custom attribute (stored as ``shv:<key>``; not part of the ontology export)."""

    def __init__(self, parent: QWidget | None = None, existing: set[str] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add attribute")
        self.existing = existing or set()
        self.label = QLineEdit()
        self.label.setPlaceholderText("e.g. Pipe material")
        self.value_type = QComboBox()
        for key, text in VALUE_TYPES:
            self.value_type.addItem(text, key)
        self.unit = QLineEdit()
        self.unit.setPlaceholderText("e.g. ft, cfs (optional)")
        self.category = QLineEdit("Attributes")
        self.choices = QLineEdit()
        self.choices.setPlaceholderText("comma-separated, for 'Choice from a list'")
        self.description = QLineEdit()
        self.error = QLabel()
        self.error.setStyleSheet("color: #cf222e;")
        form = QFormLayout()
        form.addRow("Name", self.label)
        form.addRow("Type", self.value_type)
        form.addRow("Unit", self.unit)
        form.addRow("Group", self.category)
        form.addRow("Choices", self.choices)
        form.addRow("Description", self.description)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.error)
        lay.addWidget(buttons)
        self.definition: AttributeDefinition | None = None

    def key(self) -> str:
        return "shv:" + re.sub(r"[^a-z0-9]+", "_", self.label.text().strip().lower()).strip("_")

    def _accept(self) -> None:
        label = self.label.text().strip()
        vtype = self.value_type.currentData()
        choices = tuple(c.strip() for c in self.choices.text().split(",") if c.strip())
        if not label:
            self.error.setText("Enter a name.")
            return
        if self.key() in self.existing:
            self.error.setText("An attribute with this name already exists.")
            return
        if vtype == "choice" and not choices:
            self.error.setText("List the choices, separated by commas.")
            return
        self.definition = AttributeDefinition(
            self.key(), label, vtype, self.unit.text().strip(), self.category.text().strip() or "Attributes",
            choices=choices, description=self.description.text().strip())
        self.accept()


class NodePropertiesPanel(QWidget):
    """Properties of the nodes in :meth:`show_nodes`, edited through the session (MVC)."""

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.iris: list[str] = []
        self.editor = PropertyEditor()
        self.add = QPushButton("Add attribute…")
        self.add.setToolTip("Define a new attribute for all nodes of the project")
        self.add.clicked.connect(self._add_attribute)
        self.empty = QLabel("No site selected.")
        self.empty.setObjectName("hint")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.empty)
        lay.addWidget(self.editor, 1)
        lay.addWidget(self.add)
        ctx.session.nodesChanged.connect(self._nodes_changed)
        ctx.session.projectChanged.connect(lambda: self.show_nodes([]))
        self.show_nodes([])

    def show_nodes(self, iris: list[str]) -> None:
        s = self.ctx.session
        self.iris = [i for i in iris if s.store.node(i) is not None]
        self.editor.set_nodes(node_properties(s.store, self.iris, update_node=s.update_node,
                                              set_attribute=s.set_attribute) if self.iris else [])
        self.empty.setVisible(not self.iris)
        self.editor.setVisible(bool(self.iris))
        self.add.setEnabled(bool(self.iris))

    def _nodes_changed(self, iris: list) -> None:
        if not iris:  # definitions changed: rebuild the rows
            self.show_nodes(self.iris)
        elif set(iris) & set(self.iris):
            self.editor.refresh()

    def _add_attribute(self) -> None:
        existing = {d.key for d in self.ctx.session.store.attribute_definitions()}
        dlg = AddAttributeDialog(self, existing)
        if dlg.exec() and dlg.definition is not None:
            self.ctx.session.define_attribute(dlg.definition)


__all__ = ["AddAttributeDialog", "NodePropertiesPanel"]
