"""Model composer: edit a component tree (no preset models).

The composer edits a copy of the tree and emits :attr:`ModelComposer.changed`
with the new root after every edit; it never holds state of its own beyond
the selection.  The owner writes the tree to the session, which rebuilds the
model and cascades to every view.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.components import (
    COMPONENTS,
    ComponentSpec,
    assign_aliases,
    change_type,
    new_component,
    types_for,
)
from .option_form import OptionForm

Path = tuple[tuple[str, int | None], ...]

ROLE_TEXT = {"flow": "flow", "abstraction": "abstraction", "uh": "unit hydrograph"}


def node_at(root: ComponentSpec, path: Path) -> ComponentSpec:
    node = root
    for slot, idx in path:
        v = node.slots[slot]
        node = v[idx] if idx is not None else v
    return node


def flat_prefix(root: ComponentSpec, path: Path) -> str:
    """Prefix that the built model puts on the parameters of the node at *path*."""
    prefix, node = "", root
    for slot, idx in path:
        child = node.slots[slot][idx] if idx is not None else node.slots[slot]
        if node.type == "sum":
            prefix += f"{child.alias}_"
        elif node.type == "rdii" and slot == "uhs":
            prefix += f"uh{idx + 1}_"
        elif node.type == "excess-uh" and slot == "uh":
            prefix += "uh_"
        node = child
    return prefix


def _index_names(node: ComponentSpec, prefix: str, i: int) -> list[str]:
    """Parameter-name prefixes tied to position *i* (1-based) of the node's list slot."""
    if node.type == "sum":
        return [f"{prefix}w_{i}"]
    if node.type == "rdii":
        return [f"{prefix}uh{i}_", f"{prefix}R_{i}"]
    return []


def apply_renames(names: dict[str, object], renames: dict[str, str]) -> dict[str, object]:
    """Rename keys of *names*: keys of *renames* ending in ``_`` are prefixes, others exact names.

    All renames apply simultaneously, so swaps work.
    """
    if not renames:
        return dict(names)
    exact = {k: v for k, v in renames.items() if k and not k.endswith("_")}
    prefixes = sorted((k for k in renames if k == "" or k.endswith("_")), key=len, reverse=True)
    out = {}
    for name, value in names.items():
        base = name.split("[", 1)[0]
        if base in exact:
            new = exact[base] + name[len(base):]
        else:
            p = next((p for p in prefixes if name.startswith(p)), None)
            new = renames[p] + name[len(p):] if p is not None else name
        out[new] = value
    return out


def parent_slot(root: ComponentSpec, path: Path):
    """``(parent node, slot spec, index)`` of the node at *path*, or ``None`` for the root."""
    if not path:
        return None
    parent = node_at(root, path[:-1])
    slot_name, idx = path[-1]
    return parent, COMPONENTS[parent.type].slot(slot_name), idx


class ModelComposer(QWidget):
    """Tree editor for a :class:`ComponentSpec`."""

    #: New root ComponentSpec and parameter renames (see :func:`apply_renames`).
    changed = Signal(object, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.root = new_component("rdii")
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumHeight(170)
        self.tree.currentItemChanged.connect(lambda *_: self._show_node())

        self.type_btn = QToolButton()
        self.type_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.type_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.type_btn.setMinimumWidth(200)
        self.type_btn.setToolTip("Change this component's type; children that still fit are kept")
        self.alias = QLineEdit()
        self.alias.setToolTip("Prefix of this term's parameters, e.g. 'san' gives san_baseline")
        self.alias.editingFinished.connect(self._alias_edited)
        self.description = QLabel()
        self.description.setWordWrap(True)
        self.description.setObjectName("hint")
        self.options = OptionForm()
        self.options.changed.connect(self._options_edited)

        self.add_btn = QToolButton()
        self.add_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.add_btn.setToolTip("Add a child component (for example another unit hydrograph) to the selected one")
        self.add_btn.setAccessibleName("Add component")
        self.type_btn.setAccessibleName("Component type")
        self.alias.setAccessibleName("Term prefix")
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.setToolTip("Remove the selected component and its children")
        self.remove_btn.clicked.connect(self._remove)
        self.up_btn = QPushButton("↑")
        self.up_btn.setToolTip("Move up")
        self.up_btn.clicked.connect(lambda: self._move(-1))
        self.down_btn = QPushButton("↓")
        self.down_btn.setToolTip("Move down")
        self.down_btn.clicked.connect(lambda: self._move(1))
        self.wrap_btn = QToolButton()
        self.wrap_btn.setText("Add term alongside ▾")
        self.wrap_btn.setToolTip("Turn the model into a sum and add another flow term (e.g. a sanitary pattern)")
        self.wrap_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        form = QFormLayout()
        form.addRow("Type", self.type_btn)
        self._alias_label = QLabel("Alias")
        form.addRow(self._alias_label, self.alias)
        buttons = QHBoxLayout()
        for w in (self.add_btn, self.wrap_btn, self.remove_btn, self.up_btn, self.down_btn):
            buttons.addWidget(w)
        buttons.addStretch(1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.tree, 1)
        lay.addLayout(buttons)
        lay.addLayout(form)
        lay.addWidget(self.description)
        lay.addWidget(self.options)

    # ------------------------------------------------------------------ public

    def set_root(self, root: ComponentSpec, keep_path: Path | None = None) -> None:
        current = keep_path if keep_path is not None else self._path()
        self.root = root.copy()
        self._fill()
        self._select(current)

    # ------------------------------------------------------------------ tree

    def _fill(self) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()

        def add(item_parent, node: ComponentSpec, path: Path, caption: str) -> None:
            t = COMPONENTS[node.type]
            text = f"{caption}: {t.label}" if caption else t.label
            item = QTreeWidgetItem([text])
            item.setData(0, Qt.ItemDataRole.UserRole, path)
            item.setToolTip(0, t.description)
            if isinstance(item_parent, QTreeWidget):
                item_parent.addTopLevelItem(item)
            else:
                item_parent.addChild(item)
            for s in t.slots:
                v = node.slots.get(s.name)
                if s.multiple:
                    for i, child in enumerate(v or []):
                        cap = child.alias if node.type == "sum" else f"{s.label.rstrip('s')} {i + 1}"
                        add(item, child, path + ((s.name, i),), cap)
                elif v is not None:
                    add(item, v, path + ((s.name, None),), s.label)
            item.setExpanded(True)

        add(self.tree, self.root, (), "Model")
        self.tree.blockSignals(False)

    def _path(self) -> Path:
        item = self.tree.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item is not None else ()

    def _select(self, path: Path) -> None:
        def find(item: QTreeWidgetItem) -> QTreeWidgetItem | None:
            if item.data(0, Qt.ItemDataRole.UserRole) == path:
                return item
            for i in range(item.childCount()):
                hit = find(item.child(i))
                if hit is not None:
                    return hit
            return None

        top = self.tree.topLevelItem(0)
        hit = find(top) if top is not None else None
        self.tree.setCurrentItem(hit or top)
        self._show_node()

    # ------------------------------------------------------------------ node editor

    def _show_node(self) -> None:
        path = self._path()
        try:
            node = node_at(self.root, path)
        except (KeyError, IndexError, TypeError):
            return
        t = COMPONENTS[node.type]
        ps = parent_slot(self.root, path)
        accepts = ps[1].accepts if ps else ("flow",)
        self.type_btn.setText(f"{t.label} ▾")
        menu = QMenu(self.type_btn)
        for role in ("flow", "abstraction", "uh"):
            allowed = [c for c in types_for(accepts) if c.role == role]
            if not allowed:
                continue
            if len({c.role for c in types_for(accepts)}) > 1:
                menu.addSection(ROLE_TEXT[role].capitalize())
            for c in allowed:
                act = menu.addAction(c.label)
                act.setToolTip(c.description)
                act.setCheckable(True)
                act.setChecked(c.key == node.type)
                act.triggered.connect(lambda _=False, k=c.key: self._retype(k))
        self.type_btn.setMenu(menu)
        in_sum = bool(ps) and ps[0].type == "sum"
        self.alias.setVisible(in_sum)
        self._alias_label.setVisible(in_sum)
        self.alias.setText(node.alias)
        self.description.setText(t.description)
        self.options.set_specs(t.options, node.options)

        # "Add" acts on the node's own list slot (sum terms, RDII unit hydrographs).
        multi = next((s for s in t.slots if s.multiple), None)
        self.add_btn.setVisible(multi is not None)
        if multi is not None:
            self.add_btn.setText(f"Add {multi.label.lower().rstrip('s')} ▾")
            add_menu = QMenu(self.add_btn)
            for c in types_for(multi.accepts):
                a = add_menu.addAction(c.label)
                a.setToolTip(c.description)
                a.triggered.connect(lambda _=False, k=c.key, s=multi.name: self._add_child(s, k))
            self.add_btn.setMenu(add_menu)
        removable = bool(ps) and ps[1].multiple and len(ps[0].slots[ps[1].name]) > ps[1].minimum
        self.remove_btn.setEnabled(removable)
        movable = bool(ps) and ps[1].multiple
        self.up_btn.setEnabled(movable and ps[2] > 0)
        self.down_btn.setEnabled(movable and ps[2] < len(ps[0].slots[ps[1].name]) - 1)
        self.wrap_btn.setVisible(not path and self.root.type != "sum")
        wrap_menu = QMenu(self.wrap_btn)
        for c in types_for(("flow",)):
            a: QAction = wrap_menu.addAction(c.label)
            a.triggered.connect(lambda _=False, k=c.key: self._wrap(k))
        self.wrap_btn.setMenu(wrap_menu)

    # ------------------------------------------------------------------ edits

    def _commit(self, root: ComponentSpec, select: Path, renames: dict[str, str] | None = None) -> None:
        assign_aliases(root)
        self.root = root
        self._fill()
        self._select(select)
        self.changed.emit(root.copy(), dict(renames or {}))

    def _edit(self) -> tuple[ComponentSpec, Path]:
        return self.root.copy(), self._path()

    def _retype(self, key: str) -> None:
        root, path = self._edit()
        node = node_at(root, path)
        if node.type == key:
            return
        new = change_type(node, key)
        if not path:
            root = new
        else:
            parent = node_at(root, path[:-1])
            slot, idx = path[-1]
            if idx is None:
                parent.slots[slot] = new
            else:
                parent.slots[slot][idx] = new
        self._commit(root, path)

    def _alias_edited(self) -> None:
        root, path = self._edit()
        node = node_at(root, path)
        text = "".join(ch for ch in self.alias.text().strip() if ch.isalnum() or ch == "_")
        if text and text != node.alias:
            parent = flat_prefix(root, path[:-1])
            renames = {f"{parent}{node.alias}_": f"{parent}{text}_"}
            node.alias = text
            self._commit(root, path, renames)

    def _options_edited(self) -> None:
        root, path = self._edit()
        node = node_at(root, path)
        node.options = self.options.values()
        self._commit(root, path)

    def _add_child(self, slot: str, key: str) -> None:
        root, path = self._edit()
        node = node_at(root, path)
        node.slots.setdefault(slot, []).append(new_component(key))
        self._commit(root, path + ((slot, len(node.slots[slot]) - 1),))

    def _remove(self) -> None:
        root, path = self._edit()
        ps = parent_slot(root, path)
        if not ps:
            return
        parent, slot, idx = ps
        items = parent.slots[slot.name]
        prefix = flat_prefix(root, path[:-1])
        renames: dict[str, str] = {}
        for m in range(idx + 2, len(items) + 1):  # later items shift down by one
            renames.update(dict(zip(_index_names(parent, prefix, m), _index_names(parent, prefix, m - 1))))
        del items[idx]
        self._commit(root, path[:-1], renames)

    def _move(self, d: int) -> None:
        root, path = self._edit()
        ps = parent_slot(root, path)
        if not ps:
            return
        parent, slot, idx = ps
        items = parent.slots[slot.name]
        j = idx + d
        if 0 <= j < len(items):
            prefix = flat_prefix(root, path[:-1])
            a, b = _index_names(parent, prefix, idx + 1), _index_names(parent, prefix, j + 1)
            renames = {**dict(zip(a, b)), **dict(zip(b, a))}
            items[idx], items[j] = items[j], items[idx]
            self._commit(root, path[:-1] + ((slot.name, j),), renames)

    def _wrap(self, key: str) -> None:
        root = self.root.copy()
        total = new_component("sum")
        total.slots["terms"] = [root, new_component(key)]
        assign_aliases(total)
        # Every existing parameter moves under the first term's alias.
        self._commit(total, (("terms", 1),), {"": f"{total.slots['terms'][0].alias}_"})
