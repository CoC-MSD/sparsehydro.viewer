"""Standard toolbar, status bar and progress reporting."""

from __future__ import annotations

import threading

import pytest
from PySide6.QtWidgets import QProgressBar

from helpers import spec_for
from sparsehydro_viewer.core.data import DatasetSpec, Period
from sparsehydro_viewer.core.solvers import SolverSpec

PAGES = {"Sites": 0, "Model": 1, "Events": 2, "Calibrate": 3, "Explore": 4, "Compare": 5, "Assess": 6}


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


def _load(win, qtbot, frame, csv) -> None:
    spec = DatasetSpec("sample", path=str(csv), calibration=Period("2022-05-01", "2022-05-08"))
    with qtbot.waitSignal(win.ctx.controller.result, timeout=15000):
        win.ctx.session.add_dataset(spec, frame)


def _context_texts(win) -> list[str]:
    return [a.text() for a in win.toolbar._context if not a.isSeparator()]


def test_about_credits_developer_and_partnership(window, monkeypatch) -> None:
    messages = []

    def capture(parent, title, text):
        messages.append((parent, title, text))

    monkeypatch.setattr("sparsehydro_viewer.views.main_window.QMessageBox.about", capture)
    window.about()

    assert len(messages) == 1
    parent, title, text = messages[0]
    assert parent is window and title == "SparseHydro Viewer"
    assert "Developer: Caleb Buahin" in text
    assert "A partnership between MSDGC and Hazen and Sawyer." in text
    assert "sparsehydro " in text and "PySide6 " in text and "pyqtgraph " in text


def test_toolbar_is_the_same_everywhere_with_contextual_actions(window) -> None:
    tb = window.toolbar
    fixed = [tb.run_action, tb.stop_action, *tb.chart.actions()]
    expected = {
        "Sites": {"Add site", "Draw zone", "Delete", "Edit locations", "Zoom to selection", "Basemap"},
        "Model": {"Pin shape", "Clear pinned shapes"},
        "Events": {"Previous event", "Next event", "Exclude event", "Restore excluded events"},
        "Calibrate": {"Use run settings", "Explore run", "Delete runs"},
        "Explore": {"Select knee", "Load into sliders"},
        "Compare": set(),
        "Assess": set(),
    }
    for name, row in PAGES.items():
        window.nav.setCurrentRow(row)
        assert all(a in tb.actions() for a in fixed), name
        assert expected[name] <= set(_context_texts(window)), (name, _context_texts(window))
        if not expected[name]:
            assert _context_texts(window) == []


def test_run_button_follows_the_page(window, qtbot, sample_frame, sample_csv) -> None:
    tb = window.toolbar
    window.nav.setCurrentRow(PAGES["Sites"])
    assert tb.run_action.text() == "Import data\u2026" and tb.run_action.isVisible()
    window.nav.setCurrentRow(PAGES["Model"])
    assert not tb.run_action.isVisible()  # the Model page has no run command
    window.nav.setCurrentRow(PAGES["Calibrate"])
    assert tb.run_action.text() == "Run calibration" and not tb.run_action.isEnabled()  # no dataset yet
    _load(window, qtbot, sample_frame, sample_csv)
    assert tb.run_action.isEnabled()
    assert not tb.stop_action.isEnabled()


def test_chart_actions_bind_to_the_active_chart(window, qtbot, sample_frame, sample_csv) -> None:
    tb = window.toolbar
    window.nav.setCurrentRow(PAGES["Sites"])
    assert tb.chart.plot is None  # the Map tab is not a time series
    window.pages[0].tabs.setCurrentIndex(1)
    data_plot = window.pages[0].plot
    assert tb.chart.plot is data_plot and tb.chart.fit.isEnabled()
    tb.chart.zoom.trigger()
    assert data_plot.mode == "zoom"
    tb.chart.pan.trigger()
    assert data_plot.mode == "pan"
    window.nav.setCurrentRow(PAGES["Calibrate"])  # no time-series chart
    assert tb.chart.plot is None and not tb.chart.fit.isEnabled()
    events = window.pages[PAGES["Events"]]
    window.nav.setCurrentRow(PAGES["Events"])
    assert tb.chart.plot is events.fit_plot
    events.tabs.setCurrentIndex(2)
    assert tb.chart.plot is events.conv_plot
    events.tabs.setCurrentIndex(1)  # UH shapes: not a time series
    assert tb.chart.plot is None


def test_dataset_stays_in_view_and_switches_everywhere(window, qtbot, sample_frame, sample_csv) -> None:
    sel = window.toolbar.dataset
    assert sel is not None and not sel.combo.isEnabled()  # no data yet
    _load(window, qtbot, sample_frame, sample_csv)
    with qtbot.waitSignal(window.ctx.controller.result, timeout=15000):
        window.ctx.session.add_dataset(DatasetSpec("second", path=str(sample_csv)), sample_frame)
    assert [sel.combo.itemText(i) for i in range(sel.combo.count())] == ["sample", "second"]
    assert sel.combo.currentText() == "second"
    for row in PAGES.values():  # the same selector, visible on every page
        window.nav.setCurrentRow(row)
        assert sel.isVisible()
    with qtbot.waitSignal(window.ctx.session.datasetChanged):
        sel.combo.setCurrentIndex(0)
    assert window.ctx.session.dataset_name == "sample"
    assert "Calibration: 2022-05-01" in sel.combo.toolTip()


def test_period_selection_is_a_contextual_mode(window, qtbot, sample_frame, sample_csv) -> None:
    _load(window, qtbot, sample_frame, sample_csv)
    window.nav.setCurrentRow(PAGES["Sites"])
    page = window.pages[0]
    page.tabs.setCurrentIndex(1)
    assert {"Select calibration", "Select validation", "Clear period"} <= set(_context_texts(window))
    page.periods.select["validation"].trigger()
    assert page.plot.mode == "select"
    assert not window.toolbar.chart.pan.isChecked() and not window.toolbar.chart.zoom.isChecked()
    t0 = page.plot.data_range()[0]
    with qtbot.waitSignal(window.ctx.session.periodsChanged):
        page.plot.rangeSelected.emit(t0 + 9 * 86400, t0 + 12 * 86400)
    assert page.plot.mode == "pan" and window.toolbar.chart.pan.isChecked()
    assert not page.periods.select["validation"].isChecked()
    assert window.ctx.session.dataset.validation.start.startswith("2022-05-10")


def test_status_bar_zones(window, qtbot, sample_frame, sample_csv) -> None:
    _load(window, qtbot, sample_frame, sample_csv)
    window.nav.setCurrentRow(PAGES["Sites"])
    window.pages[0].tabs.setCurrentIndex(1)
    status = window.status
    text = status.context.text()
    assert "sample" in text and "parameters" in text and "calibration: 2022-05-01" in text
    plot = window.pages[0].plot
    plot.cursorMoved.emit(plot.data_range()[0] + 3600.0, 1.25)
    assert status.cursor.text() == "2022-05-01 01:00   1.25"
    window.nav.setCurrentRow(PAGES["Calibrate"])
    assert status.cursor.text() == ""


def test_activity_indicator_shows_job_progress(window, qtbot) -> None:
    gate = threading.Event()
    reported = threading.Event()

    def work(ctx):
        ctx.progress("half way", 0.5)
        reported.set()
        gate.wait(10)
        return 1

    window.ctx.jobs.submit("Test job", work)
    reported.wait(5)
    ind = window.status.activity
    qtbot.waitUntil(lambda: "Test job" in ind.label.text(), timeout=3000)
    assert ind.bar.isVisible() and ind.bar.maximum() == 1000 and ind.bar.value() == 500
    gate.set()
    window.ctx.jobs.wait(5000)
    qtbot.waitUntil(lambda: ind.label.text() == "Ready", timeout=3000)
    assert not ind.bar.isVisible()


@pytest.mark.slow
def test_calibration_progress_bar_and_stop(window, qtbot, sample_frame, sample_csv) -> None:
    s = window.ctx.session
    _load(window, qtbot, sample_frame, sample_csv)
    with qtbot.waitSignal(window.ctx.controller.result, timeout=15000):
        s.set_model(spec_for("gamma-uh"))
    s.set_solver(SolverSpec("nsga2", {"pop_size": 10, "n_gen": 200000}))
    page = window.pages[PAGES["Calibrate"]]
    page._load_from_session()
    window.nav.setCurrentRow(PAGES["Calibrate"])
    window.toolbar.run_action.trigger()
    rid = s.project.runs[-1].id
    qtbot.waitUntil(lambda: len(s.run(rid).history) > 2, timeout=60000)
    row = page._row_of(rid)
    bar = page.table.cellWidget(row, 5)
    assert isinstance(bar, QProgressBar) and bar.maximum() == 1000
    assert "generation" in bar.format()
    frac, text = window.ctx.calibration.progress_info(rid)
    assert frac is not None and 0 < frac < 0.01 and text.startswith("generation")
    assert window.toolbar.stop_action.isEnabled()
    qtbot.waitUntil(lambda: "Calibrating" in window.status.activity.label.text(), timeout=3000)
    with qtbot.waitSignal(window.ctx.calibration.finished, timeout=15000):
        window.toolbar.stop_action.trigger()
    assert s.run(rid).status == "cancelled"
    assert page.table.cellWidget(row, 5) is None
    qtbot.waitUntil(lambda: not window.toolbar.stop_action.isEnabled(), timeout=3000)
