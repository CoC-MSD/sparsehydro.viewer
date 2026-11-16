"""The rain gauge / temperature pickers, and what follows a change across the application."""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtWidgets import QMessageBox

from sparsehydro_viewer.core.data import DatasetSpec


@pytest.fixture
def window(qtbot, short_frame):
    from PySide6.QtCore import QSettings

    from sparsehydro_viewer.app import create_app
    from sparsehydro_viewer.views.main_window import MainWindow

    create_app()
    QSettings().setValue("map/basemap", False)
    win = MainWindow()
    win.show()
    s = win.ctx.session
    s.add_dataset(DatasetSpec("B"), short_frame.assign(rain=short_frame["rain"] * 2.0, temperature_c=12.5))
    s.add_dataset(DatasetSpec("A"), short_frame)  # current
    yield win
    s.set_dirty(False)
    win.ctx.calibration.shutdown()
    win.close()
    win.deleteLater()


def _page(win, title):
    return next(p for p in win.pages if p.title == title)


def test_picker_shows_the_current_inputs_and_every_candidate(window) -> None:
    s = window.ctx.session
    bar = _page(window, "Model").inputs
    assert bar.isEnabled() and bar.rain.count() == 2 and bar.temperature.count() == 2
    assert bar.rain.currentData() == s.dataset.rain_stream and bar.temperature.currentData() is None
    assert "A rain @ A" in bar.rain.currentText() and "5 min" in bar.rain.currentText()
    assert bar.note.text() == ""


def test_choosing_another_gauge_rebuilds_the_dataset_everywhere(window, qtbot) -> None:
    s = window.ctx.session
    model, sites = _page(window, "Model"), _page(window, "Sites")
    before = s.frame()["rain"].to_numpy().copy()
    b = s.project.dataset("B")
    s.update_node(s.dataset.site_iri, geometry="POINT (-84.50 39.10)")
    s.update_node(b.site_iri, geometry="POINT (-84.40 39.20)")
    assert not sites.map._links
    bar = model.inputs
    with qtbot.waitSignal(s.datasetDataChanged) as sig, qtbot.waitSignal(window.ctx.controller.result, timeout=20000):
        bar.rain.setCurrentIndex(bar.rain.findData(b.rain_stream))
    assert sig.args == ["A"]
    np.testing.assert_allclose(s.frame()["rain"], before * 2.0)
    assert s.dirty
    assert "another site" in bar.note.text()
    # The other picker (Sites page) follows, as do the hints that name the inputs.
    assert sites.inputs.rain.currentData() == b.rain_stream
    assert "B rain @ B" in _page(window, "Calibrate").launch_hint.text()
    assert "B rain @ B" in window.params.context.text()
    assert "B rain @ B" in window.toolbar.dataset.combo.toolTip()
    assert sites.map._links  # the flow site is linked to its gauge on the map

    bar.temperature.setCurrentIndex(bar.temperature.findData(b.temperature_stream))
    assert "temperature_c" in s.frame().columns
    assert "temperature: B temperature_c @ B" in s.inputs_text()


def test_a_series_that_does_not_overlap_is_refused_and_the_choice_put_back(window, short_frame, monkeypatch) -> None:
    import pandas as pd

    s = window.ctx.session
    s.add_dataset(DatasetSpec("C"), short_frame.assign(datetime=short_frame["datetime"] + pd.Timedelta(days=400)))
    s.select_dataset("A")
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a[2]))
    bar = _page(window, "Model").inputs
    own = s.dataset.rain_stream
    bar.rain.setCurrentIndex(bar.rain.findData(s.project.dataset("C").rain_stream))
    assert shown and "do not overlap" in shown[0]
    assert s.dataset.rain_stream == own and bar.rain.currentData() == own


def test_assess_names_the_working_model_and_follows_a_rename(window) -> None:
    s = window.ctx.session
    page = _page(window, "Assess")
    s.set_model_label("Two-path RDII")
    assert page.source.itemText(0) == "Working model: Two-path RDII (current slider values)"
    assert page._source()[3] == "Two-path RDII (working model)"
    s.set_model_label("Renamed")
    assert "Renamed" in page.source.itemText(0)
