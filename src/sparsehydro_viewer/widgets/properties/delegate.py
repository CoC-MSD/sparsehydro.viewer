"""Typed editors for :class:`PropertyModel` values."""

from __future__ import annotations

from typing import Any

import pandas as pd
from PySide6.QtCore import QAbstractItemModel, QDateTime, QModelIndex, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateTimeEdit,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolButton,
    QWidget,
)

from .model import NodeRole
from .node import PropertyNode

_BIG = 1e15


class _FileEditor(QWidget):
    """Line edit + browse button; the browse dialog keeps the editor open."""

    def __init__(self, parent: QWidget, file_filter: str) -> None:
        super().__init__(parent)
        self.edit = QLineEdit()
        self.button = QToolButton()
        self.button.setText("…")
        self.button.clicked.connect(self._browse)
        self.filter = file_filter
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        lay.addWidget(self.edit, 1)
        lay.addWidget(self.button)
        self.setFocusProxy(self.edit)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose file", self.edit.text(), self.filter or "All files (*)")
        if path:
            self.edit.setText(path)


class PropertyDelegate(QStyledItemDelegate):
    def _node(self, index: QModelIndex) -> PropertyNode:
        return index.data(NodeRole)

    def createEditor(self, parent: QWidget, option: QStyleOptionViewItem, index: QModelIndex) -> QWidget:  # noqa: N802
        node = self._node(index)
        h = node.hints
        t = node.value_type
        if t == "float":
            w = QDoubleSpinBox(parent)
            w.setDecimals(h.decimals if h.decimals is not None else 6)
            w.setRange(h.minimum if h.minimum is not None else -_BIG, h.maximum if h.maximum is not None else _BIG)
            if h.unit:
                w.setSuffix(f" {h.unit}")
            w.setKeyboardTracking(False)
            return w
        if t == "int":
            w = QSpinBox(parent)
            w.setRange(int(h.minimum) if h.minimum is not None else -2**31 + 1,
                       int(h.maximum) if h.maximum is not None else 2**31 - 1)
            if h.unit:
                w.setSuffix(f" {h.unit}")
            return w
        if t == "choice":
            w = QComboBox(parent)
            for c in h.choices:
                w.addItem(h.choice_labels.get(c, str(c)), c)
            # Combos commit as soon as a choice is made.
            w.activated.connect(lambda *_: self.commitData.emit(w))
            return w
        if t == "datetime":
            w = QDateTimeEdit(parent)
            w.setDisplayFormat("yyyy-MM-dd HH:mm")
            w.setCalendarPopup(True)
            return w
        if t == "text":
            return QPlainTextEdit(parent)
        if t == "file":
            return _FileEditor(parent, h.file_filter)
        return QLineEdit(parent)

    def setEditorData(self, editor: QWidget, index: QModelIndex) -> None:  # noqa: N802
        value: Any = index.data(Qt.ItemDataRole.EditRole)
        if isinstance(editor, QDoubleSpinBox):
            editor.setValue(float(value) if value is not None else 0.0)
        elif isinstance(editor, QSpinBox):
            editor.setValue(int(value) if value is not None else 0)
        elif isinstance(editor, QComboBox):
            editor.setCurrentIndex(max(0, editor.findData(value)))
        elif isinstance(editor, QDateTimeEdit):
            ts = pd.Timestamp(value) if value else pd.Timestamp.now().floor("min")
            editor.setDateTime(QDateTime(ts.to_pydatetime()))
        elif isinstance(editor, QPlainTextEdit):
            editor.setPlainText("" if value is None else str(value))
        elif isinstance(editor, _FileEditor):
            editor.edit.setText("" if value is None else str(value))
        elif isinstance(editor, QLineEdit):
            editor.setText("" if value is None else str(value))

    def setModelData(self, editor: QWidget, model: QAbstractItemModel, index: QModelIndex) -> None:  # noqa: N802
        if isinstance(editor, QDoubleSpinBox):
            value: Any = editor.value()
        elif isinstance(editor, QSpinBox):
            value = editor.value()
        elif isinstance(editor, QComboBox):
            value = editor.currentData()
        elif isinstance(editor, QDateTimeEdit):
            value = editor.dateTime().toPython().strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(editor, QPlainTextEdit):
            value = editor.toPlainText()
        elif isinstance(editor, _FileEditor):
            value = editor.edit.text()
        elif isinstance(editor, QLineEdit):
            value = editor.text()
        else:
            return
        model.setData(index, value, Qt.ItemDataRole.EditRole)

    def updateEditorGeometry(self, editor: QWidget, option: QStyleOptionViewItem, index: QModelIndex) -> None:  # noqa: N802
        rect = option.rect
        if isinstance(editor, QPlainTextEdit):
            rect.setHeight(max(rect.height(), 80))
        editor.setGeometry(rect)


__all__ = ["PropertyDelegate"]
