"""Main window: navigation rail, workspace pages, parameter dock and job/log dock."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, QSize, Qt, Signal
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, __version__, theme
from ..core.project import Project
from ..services import CalibrationService, JobManager, LiveEvaluationService
from ..session import Session
from ..widgets import ParameterPanel
from .calibrate_page import CalibratePage
from .common import num_item, text_item
from .compare_page import ComparePage
from .context import AppContext, LiveController
from .data_page import DataPage
from .events_page import EventsPage
from .explore_page import ExplorePage
from .model_page import ModelPage

MAX_RECENT = 8


class _LogBridge(QObject, logging.Handler):
    message = Signal(str)

    def __init__(self) -> None:
        QObject.__init__(self)
        logging.Handler.__init__(self, level=logging.INFO)
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:  # type: ignore[override]
        try:
            self.message.emit(self.format(record))
        except RuntimeError:  # widget already destroyed at shutdown
            pass


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = QSettings()
        session = Session(self)
        jobs = JobManager(self)
        calibration = CalibrationService(self)
        live = LiveEvaluationService(self)
        controller = LiveController(session, live)
        self.ctx = AppContext(session, jobs, calibration, live, controller)

        # -- pages -------------------------------------------------------------
        self.nav = QListWidget()
        self.nav.setObjectName("navRail")
        self.nav.setFixedWidth(118)
        self.stack = QStackedWidget()
        self.explore = ExplorePage(self.ctx)
        self.pages: list[QWidget] = [
            DataPage(self.ctx), ModelPage(self.ctx), EventsPage(self.ctx),
            CalibratePage(self.ctx, show_explore=self.show_explore), self.explore, ComparePage(self.ctx),
        ]
        for i, page in enumerate(self.pages):
            self.stack.addWidget(page)
            item = QListWidgetItem(page.title)
            item.setToolTip(f"Ctrl+{i + 1}")
            item.setSizeHint(QSize(100, 40))
            self.nav.addItem(item)
            act = QAction(self)
            act.setShortcut(QKeySequence(f"Ctrl+{i + 1}"))
            act.triggered.connect(lambda _=False, i=i: self.nav.setCurrentRow(i))
            self.addAction(act)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.currentRowChanged.connect(self._page_changed)
        central = QWidget()
        cl = QHBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self.nav)
        cl.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        # -- parameter dock ------------------------------------------------------
        # The dock edits the session's working model only; it is shown on the pages that use it.
        self.params = ParameterPanel()
        self.params.setMinimumWidth(500)
        self.param_dock = QDockWidget("Working model", self)
        self.param_dock.setObjectName("paramDock")
        self.param_dock.setWidget(self.params)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.param_dock)
        self.params.valuesEdited.connect(session.set_values)
        self.params.boundsEdited.connect(lambda n, lo, hi: session.edit_parameter(n, lower=lo, upper=hi))
        self.params.calibrateToggled.connect(lambda n, on: session.edit_parameter(n, calibrate=on))
        self.params.resetRequested.connect(session.reset_parameters)
        session.modelChanged.connect(self._rebuild_params)
        session.projectChanged.connect(self._rebuild_params)
        session.valuesChanged.connect(self.params.set_values)
        session.parametersEdited.connect(self._params_edited)
        for sig in (session.modelChanged, session.modelRenamed, session.datasetChanged, session.periodsChanged,
                    session.parametersEdited, session.projectChanged):
            sig.connect(self._update_param_context)

        # -- jobs / log dock -------------------------------------------------------
        self.job_table = QTableWidget(0, 4)
        self.job_table.setHorizontalHeaderLabels(["Job", "State", "Progress", "Message"])
        self.job_table.verticalHeader().setVisible(False)
        self.job_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.job_table.horizontalHeader().setStretchLastSection(True)
        self.job_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        cancel = QPushButton("Cancel selected job")
        cancel.clicked.connect(self._cancel_job)
        jw = QWidget()
        jl = QVBoxLayout(jw)
        jl.setContentsMargins(4, 4, 4, 4)
        jl.addWidget(self.job_table)
        jl.addWidget(cancel, alignment=Qt.AlignmentFlag.AlignRight)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        tabs = QTabWidget()
        tabs.addTab(jw, "Jobs")
        tabs.addTab(self.log_view, "Log")
        self.job_dock = QDockWidget("Activity", self)
        self.job_dock.setObjectName("jobDock")
        self.job_dock.setWidget(tabs)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.job_dock)
        self.job_dock.hide()
        jobs.jobAdded.connect(self._job_row)
        jobs.jobChanged.connect(self._job_row)
        self._log_bridge = _LogBridge()
        self._log_bridge.message.connect(self.log_view.appendPlainText)
        logging.getLogger().addHandler(self._log_bridge)

        # -- status bar --------------------------------------------------------------
        self.status_model = QLabel()
        self.status_jobs = QLabel()
        self.statusBar().addWidget(self.status_model, 1)
        self.statusBar().addPermanentWidget(self.status_jobs)
        session.modelChanged.connect(self._update_status)
        session.parametersEdited.connect(self._update_status)
        session.datasetChanged.connect(self._update_status)
        calibration.started.connect(lambda *_: self._update_status())
        calibration.finished.connect(lambda *_: self._update_status())
        session.dirtyChanged.connect(lambda *_: self._update_title())
        controller.unavailable.connect(lambda msg: self.statusBar().showMessage(msg, 5000))

        self._build_menus()
        self.resize(1500, 920)
        geo = self.settings.value("window/geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        state = self.settings.value("window/state")
        if state is not None:
            self.restoreState(state)
        self.nav.setCurrentRow(0)
        self._rebuild_params()
        self._update_param_context()
        self._update_status()
        self._update_title()

    # ------------------------------------------------------------------ menus

    def _build_menus(self) -> None:
        mb = self.menuBar()
        f = mb.addMenu("&File")
        self._add(f, "&New project", self.new_project, QKeySequence.StandardKey.New)
        self._add(f, "&Open project...", self.open_project_dialog, QKeySequence.StandardKey.Open)
        self.recent_menu = f.addMenu("Open &recent")
        self._fill_recent()
        f.addSeparator()
        self._add(f, "&Save project", self.save_project, QKeySequence.StandardKey.Save)
        self._add(f, "Save project &as...", self.save_project_as, QKeySequence.StandardKey.SaveAs)
        f.addSeparator()
        self._add(f, "E&xit", self.close, QKeySequence.StandardKey.Quit)
        v = mb.addMenu("&View")
        v.addAction(self.param_dock.toggleViewAction())
        v.addAction(self.job_dock.toggleViewAction())
        v.addSeparator()
        self._add(v, "&Light theme", lambda: self.set_theme("light"))
        self._add(v, "&Dark theme", lambda: self.set_theme("dark"))
        h = mb.addMenu("&Help")
        self._add(h, "&About", self.about)

    def _add(self, menu, text, slot, shortcut=None) -> QAction:
        act = menu.addAction(text)
        act.triggered.connect(slot)
        if shortcut is not None:
            act.setShortcut(QKeySequence(shortcut))
        return act

    def _fill_recent(self) -> None:
        self.recent_menu.clear()
        recent = [p for p in (self.settings.value("recent", []) or []) if p]
        for p in recent:
            act = self.recent_menu.addAction(p)
            act.triggered.connect(lambda _=False, p=p: self.open_project(p))
        self.recent_menu.setEnabled(bool(recent))

    def _remember(self, folder: str) -> None:
        recent = [p for p in (self.settings.value("recent", []) or []) if p and p != folder]
        self.settings.setValue("recent", [folder] + recent[: MAX_RECENT - 1])
        self._fill_recent()

    # ------------------------------------------------------------------ project

    def _confirm_discard(self) -> bool:
        if not self.ctx.session.dirty:
            return True
        r = QMessageBox.question(self, APP_NAME, "Save changes to the current project?",
                                 QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                                 | QMessageBox.StandardButton.Cancel)
        if r == QMessageBox.StandardButton.Cancel:
            return False
        if r == QMessageBox.StandardButton.Save:
            return self.save_project()
        return True

    def new_project(self) -> None:
        if self._confirm_discard():
            self.ctx.session.set_project(Project())
            self._update_title()

    def open_project_dialog(self) -> None:
        if not self._confirm_discard():
            return
        folder = QFileDialog.getExistingDirectory(self, "Open project folder", self.settings.value("last_dir", ""))
        if folder:
            self.open_project(folder, confirm=False)

    def open_project(self, folder: str, confirm: bool = True) -> None:
        if confirm and not self._confirm_discard():
            return
        if not Project.is_project_folder(folder):
            QMessageBox.warning(self, APP_NAME, f"{folder} is not a project folder (no project.json).")
            return
        try:
            project = Project.load(folder)
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, f"Could not open {folder}:\n{exc}")
            return
        self.ctx.session.set_project(project)
        self.settings.setValue("last_dir", str(Path(folder).parent))
        self._remember(str(Path(folder)))
        self._update_title()

    def save_project(self) -> bool:
        if self.ctx.session.project.folder is None:
            return self.save_project_as()
        try:
            self.ctx.session.save_project()
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, f"Save failed:\n{exc}")
            return False
        self.statusBar().showMessage("Project saved", 3000)
        return True

    def save_project_as(self) -> bool:
        folder = QFileDialog.getExistingDirectory(self, "Choose or create a project folder",
                                                  self.settings.value("last_dir", ""))
        if not folder:
            return False
        overwriting = Project.is_project_folder(folder) and folder != str(self.ctx.session.project.folder or "")
        if overwriting and QMessageBox.question(self, APP_NAME, f"{folder} already holds a project. Overwrite it?") \
                != QMessageBox.StandardButton.Yes:
            return False
        self.ctx.session.project.name = Path(folder).name
        try:
            self.ctx.session.save_project(folder)
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, f"Save failed:\n{exc}")
            return False
        self._remember(folder)
        self._update_title()
        return True

    # ------------------------------------------------------------------ parameters

    def _rebuild_params(self) -> None:
        self.params.set_parameters(self.ctx.session.parameter_info())

    def _params_edited(self) -> None:
        # Bounds/flags may have changed elsewhere (Reset all, Calibrate's "Use settings"): mirror them.
        if set(self.params.rows) != set(self.ctx.session.values):
            self._rebuild_params()
        else:
            self.params.set_calibrate_flags(self.ctx.session.calibrate_flags())

    def _update_param_context(self) -> None:
        s = self.ctx.session
        ds = s.dataset
        if ds is None:
            data = "no dataset loaded"
        else:
            period = "whole record" if ds.calibration.is_open else \
                f"{ds.calibration.start[:10]} to {(ds.calibration.end or '')[:10]}"
            data = f"{ds.name}, calibration {period}"
        self.params.set_context(
            f"<b>Working model:</b> {s.model_spec.display_label}<br>"
            f"<span style='font-size:9pt'>{data}<br>Drives the Model page simulation, the ★ point in "
            "Explore and Compare, and is the starting point for new Calibrate runs.</span>")

    def _page_changed(self, row: int) -> None:
        """Show the working-model dock only where it has an effect."""
        uses = getattr(self.pages[row], "uses_working_model", False)
        self.param_dock.setVisible(uses)

    # ------------------------------------------------------------------ jobs

    def _job_row(self, job_id: int) -> None:
        info = self.ctx.jobs.info(job_id)
        rows = {self.job_table.item(r, 0).data(Qt.ItemDataRole.UserRole): r for r in range(self.job_table.rowCount())}
        r = rows.get(job_id)
        if r is None:
            r = 0
            self.job_table.insertRow(0)
        self.job_table.setItem(r, 0, text_item(info.label, job_id))
        self.job_table.setItem(r, 1, text_item(info.state))
        self.job_table.setItem(r, 2, num_item(info.fraction * 100 if info.fraction >= 0 else None, "{:.0f}%"))
        self.job_table.setItem(r, 3, text_item(info.text))
        running = sum(j.state == "running" for j in self.ctx.jobs.jobs())
        self._jobs_running = running
        self._update_status()
        if info.state == "failed":
            self.job_dock.show()

    def _cancel_job(self) -> None:
        r = self.job_table.currentRow()
        if r >= 0:
            self.ctx.jobs.cancel(self.job_table.item(r, 0).data(Qt.ItemDataRole.UserRole))

    # ------------------------------------------------------------------ status

    def _update_status(self) -> None:
        s = self.ctx.session
        info = s.parameter_info()
        k = sum(p.calibrate for p in info)
        ds = s.dataset_name or "no dataset"
        self.status_model.setText(f"{ds}  |  {s.model_spec.display_label}: {len(info)} parameters, {k} calibrated")
        n_cal = self.ctx.calibration.active_count
        n_jobs = getattr(self, "_jobs_running", 0)
        parts = []
        if n_cal:
            parts.append(f"{n_cal} calibration run(s) active")
        if n_jobs:
            parts.append(f"{n_jobs} background job(s)")
        self.status_jobs.setText("   ".join(parts))

    def _update_title(self) -> None:
        p = self.ctx.session.project
        name = p.name if p.folder else "Untitled"
        self.setWindowTitle(f"{name}{' *' if self.ctx.session.dirty else ''} - {APP_NAME}")

    def show_explore(self, run_id: str) -> None:
        self.explore.show_run(run_id)
        self.nav.setCurrentRow(self.pages.index(self.explore))

    def set_theme(self, name: str) -> None:
        theme.apply(QApplication.instance(), theme.DARK if name == "dark" else theme.LIGHT)
        self.settings.setValue("theme", name)
        QMessageBox.information(self, APP_NAME, "Plots pick up the new theme when they are next redrawn; restart "
                                                "the application to restyle everything.")

    def about(self) -> None:
        from ..core import versions

        v = versions()
        QMessageBox.about(self, APP_NAME, f"<b>{APP_NAME}</b> {__version__}<br>"
                                          f"sparsehydro {v['sparsehydro']}<br>PySide6 {v['PySide6']} "
                                          f"(Qt, LGPLv3)<br>pyqtgraph {v['pyqtgraph']}")

    # ------------------------------------------------------------------ close

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self.ctx.calibration.active_count:
            r = QMessageBox.question(self, APP_NAME, "Calibration runs are still active. Stop them and exit?")
            if r != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        if not self._confirm_discard():
            event.ignore()
            return
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("window/state", self.saveState())
        self.shutdown()
        event.accept()

    def shutdown(self) -> None:
        if getattr(self, "_shut_down", False):
            return
        self._shut_down = True
        logging.getLogger().removeHandler(self._log_bridge)
        self.ctx.calibration.shutdown()
        self.ctx.live.shutdown()
        self.ctx.jobs.wait(5000)
