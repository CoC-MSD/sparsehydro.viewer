"""Property editor (QPropertyModel-style) and node properties."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QAbstractItemModelTester
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QStyleOptionViewItem

from sparsehydro_viewer.core.options import OptionSpec
from sparsehydro_viewer.core.store import ProjectStore
from sparsehydro_viewer.widgets.properties import (
    MIXED_TEXT,
    Hints,
    PropertyDelegate,
    PropertyEditor,
    PropertyModel,
    PropertyNode,
    from_option_specs,
    node_properties,
)


def _sample_nodes(state: dict) -> list[PropertyNode]:
    def node(name, vtype, **hints):
        return PropertyNode(name, vtype, lambda n=name: state[n], lambda v, n=name: state.__setitem__(n, v),
                            Hints(**hints))

    return [
        PropertyNode.group("Numbers", [node("area", "float", unit="acres", minimum=0, maximum=1e4, decimals=2,
                                            default=10.0),
                                       node("count", "int", minimum=1, maximum=9)]),
        PropertyNode.group("Other", [node("name", "str"), node("on", "bool"),
                                     node("kind", "choice", choices=("a", "b"), choice_labels={"a": "Alpha", "b": "Beta"}),
                                     PropertyNode("ro", "str", lambda: "fixed", hints=Hints(readonly=True))]),
    ]


def test_model_passes_qt_model_tester(qtbot) -> None:
    state = {"area": 12.5, "count": 3, "name": "x", "on": True, "kind": "b"}
    model = PropertyModel()
    tester = QAbstractItemModelTester(model, QAbstractItemModelTester.FailureReportingMode.Fatal)
    model.set_nodes(_sample_nodes(state))
    model.refresh()
    assert tester is not None and model.rowCount() == 2


def test_display_edit_and_checkbox(qtbot) -> None:
    state = {"area": 12.5, "count": 3, "name": "x", "on": True, "kind": "b"}
    model = PropertyModel()
    model.set_nodes(_sample_nodes(state))
    numbers, other = model.index(0, 0), model.index(1, 0)
    area = model.index(0, 1, numbers)
    assert model.data(area) == "12.50 acres"
    assert model.data(model.index(2, 1, other)) == "Beta"
    with qtbot.waitSignal(model.valueChanged):
        assert model.setData(area, 40.0)
    assert state["area"] == 40.0
    on = model.index(1, 1, other)
    assert model.flags(on) & Qt.ItemFlag.ItemIsUserCheckable
    model.setData(on, Qt.CheckState.Unchecked.value, Qt.ItemDataRole.CheckStateRole)
    assert state["on"] is False
    ro = model.index(3, 1, other)
    assert not model.flags(ro) & Qt.ItemFlag.ItemIsEditable and not model.setData(ro, "y")
    assert model.reset_to_default(model.index(0, 0, numbers)) and state["area"] == 10.0


def test_delegate_editors_follow_hints(qtbot) -> None:
    state = {"area": 12.5, "count": 3, "name": "x", "on": True, "kind": "b"}
    view = PropertyEditor()
    qtbot.addWidget(view)
    view.set_nodes(_sample_nodes(state))
    model = view.property_model
    delegate: PropertyDelegate = view.itemDelegate()
    area = model.index(0, 1, model.index(0, 0))
    ed = delegate.createEditor(view.viewport(), QStyleOptionViewItem(), area)
    assert isinstance(ed, QDoubleSpinBox) and ed.maximum() == 1e4 and ed.decimals() == 2 and ed.suffix() == " acres"
    delegate.setEditorData(ed, area)
    assert ed.value() == 12.5
    ed.setValue(99.0)
    delegate.setModelData(ed, model, area)
    assert state["area"] == 99.0
    kind = model.index(2, 1, model.index(1, 0))
    combo = delegate.createEditor(view.viewport(), QStyleOptionViewItem(), kind)
    assert isinstance(combo, QComboBox) and combo.itemText(0) == "Alpha"


def test_option_specs_adapter(qtbot) -> None:
    seen = []
    nodes = from_option_specs([OptionSpec("pop_size", "int", 50, minimum=4), OptionSpec("seed", "int", 42)],
                              {"pop_size": 80}, seen.append)
    model = PropertyModel()
    model.set_nodes(nodes)
    assert model.data(model.index(0, 1)) == "80"
    model.setData(model.index(1, 1), 7)
    assert seen[-1] == {"pop_size": 80, "seed": 7}


def test_node_properties_single_and_multiple(qtbot) -> None:
    st = ProjectStore.memory()
    a = st.add_site("A", geometry="POINT (-84.5 39.1)")
    b = st.add_site("B")
    st.set_attribute(a, "shv:contributing_area", 10.0)
    st.set_attribute(b, "shv:contributing_area", 20.0)
    calls = []

    def update_node(iri, **f):
        calls.append(("node", iri, f))
        st.update_node(iri, **f)

    def set_attribute(iri, k, v):
        calls.append(("attr", iri, k, v))
        st.set_attribute(iri, k, v)

    model = PropertyModel()
    model.set_nodes(node_properties(st, [a], update_node=update_node, set_attribute=set_attribute))
    loc = model.index(1, 0)
    lon = model.index(0, 1, loc)
    assert model.data(lon) == "-84.500000 °"
    model.setData(model.index(1, 1, loc), 39.25)
    assert st.node(a).geometry == "POINT (-84.5000000 39.2500000)"

    model.set_nodes(node_properties(st, [a, b], update_node=update_node, set_attribute=set_attribute))
    hydro = next(model.index(r, 0) for r in range(model.rowCount()) if model.data(model.index(r, 0)) == "Hydrology")
    area_row = next(r for r in range(model.rowCount(hydro))
                    if model.data(model.index(r, 0, hydro)) == "Contributing area")
    area = model.index(area_row, 1, hydro)
    assert model.data(area) == MIXED_TEXT
    model.setData(area, 15.0)
    assert st.attributes(a)["shv:contributing_area"] == st.attributes(b)["shv:contributing_area"] == 15.0
    assert not model.flags(model.index(0, 1, model.index(1, 0))) & Qt.ItemFlag.ItemIsEditable  # location: single only


@pytest.fixture
def window(qtbot):
    from sparsehydro_viewer.app import create_app
    from sparsehydro_viewer.views.main_window import MainWindow

    create_app()
    win = MainWindow()
    win.show()
    yield win
    win.ctx.session.set_dirty(False)
    win.ctx.calibration.shutdown()
    win.close()
    win.deleteLater()


def test_site_properties_on_data_page_save_and_reopen(window, qtbot, sample_frame, sample_csv, tmp_path) -> None:
    from sparsehydro_viewer.core.data import DatasetSpec
    from sparsehydro_viewer.core.project import Project

    s = window.ctx.session
    with qtbot.waitSignal(window.ctx.controller.result, timeout=15000):
        s.add_dataset(DatasetSpec("MH-12", path=str(sample_csv)), sample_frame)
    panel = window.pages[0].site_props
    site = s.dataset.site_iri
    assert panel.iris == [site]
    model = panel.editor.property_model
    general = model.index(0, 0)
    with qtbot.waitSignal(s.nodesChanged):
        model.setData(model.index(1, 1, general), "Manhole 12")  # Name
    assert s.store.node(site).label == "Manhole 12" and s.dirty
    s.set_attribute(site, "shv:capacity_flow", 3.5)
    path = tmp_path / "proj.shproj"
    s.save_project(str(path))
    back = Project.load(path)
    assert back.store.node(site).label == "Manhole 12"
    assert back.store.attributes(site)["shv:capacity_flow"] == 3.5
    window.open_project(str(path), confirm=False)
    assert window.ctx.session.frame() is not None and len(window.ctx.session.frame()) == len(sample_frame)
