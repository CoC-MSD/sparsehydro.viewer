"""The application's single toolbar.

Layout, identical on every page::

    [New Open Save] | [Run <page command>] [Stop] | [Pan Zoom Fit AutoY Export] | [page actions...] | [docks]

The Run and Stop buttons call the current page; the chart buttons act on the
page's active chart; the page actions are swapped when the page changes.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QSizePolicy, QToolBar, QToolButton, QWidget

from ...resources import icon
from ...widgets.chart_actions import ChartActions
from .page import Page


class MainToolBar(QToolBar):
    def __init__(self, parent: QWidget, project_actions: list[QAction], view_actions: list[QAction]) -> None:
        super().__init__("Main toolbar", parent)
        self.setObjectName("mainToolBar")
        self.setMovable(False)
        self.setIconSize(QSize(20, 20))
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.page: Page | None = None

        for a in project_actions:
            self.addAction(a)
        self.addSeparator()
        self.run_action = QAction(icon("run", "#1a7f37"), "Run", self)
        self.run_action.setShortcut(QKeySequence("F5"))
        self.run_action.triggered.connect(self._run)
        self.stop_action = QAction(icon("stop", "#cf222e"), "Stop", self)
        self.stop_action.setShortcut(QKeySequence("Shift+F5"))
        self.stop_action.setToolTip("Stop what this page started  [Shift+F5]")
        self.stop_action.triggered.connect(self._stop)
        self.addAction(self.run_action)
        self.addAction(self.stop_action)
        run_button = self.widgetForAction(self.run_action)
        if isinstance(run_button, QToolButton):
            run_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addSeparator()
        self.chart = ChartActions(parent)
        for a in self.chart.actions():
            self.addAction(a)
        self._context_start = self.addSeparator()
        self._context: list[QAction] = []
        self._context_end = self.addSeparator()
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.addWidget(spacer)
        for a in view_actions:
            self.addAction(a)

    # ------------------------------------------------------------------

    def set_page(self, page: Page) -> None:
        if self.page is not None:
            try:
                self.page.contextChanged.disconnect(self.refresh)
            except (RuntimeError, TypeError):
                pass
        self.page = page
        page.contextChanged.connect(self.refresh)
        self._context_ids = None
        self.refresh()

    def _rebuild_context(self, actions) -> None:
        for a in self._context:
            self.removeAction(a)
        self._context = []
        for a in actions:
            if a is None:
                sep = QAction(self)
                sep.setSeparator(True)
                a = sep
            self.insertAction(self._context_end, a)
            self._context.append(a)
            if a.menu() is not None:
                button = self.widgetForAction(a)
                if isinstance(button, QToolButton):
                    button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._context_end.setVisible(bool(self._context))

    def refresh(self) -> None:
        """Re-read the page's contextual actions, Run/Stop state and active chart."""
        page = self.page
        if page is None:
            return
        actions = page.context_actions()
        ids = [id(a) for a in actions]
        if ids != getattr(self, "_context_ids", None):  # the set depends on the page's state (e.g. its tab)
            self._context_ids = ids
            self._rebuild_context(actions)
        text = page.primary_text
        self.run_action.setText(text or "Run")
        self.run_action.setToolTip((page.primary_tip or text or "This page has no run command") + "  [F5]")
        self.run_action.setEnabled(bool(text) and page.primary_enabled())
        self.run_action.setVisible(bool(text))
        self.stop_action.setEnabled(page.stop_enabled())
        self.chart.bind(page.active_chart())

    def _run(self) -> None:
        if self.page is not None and self.page.primary_enabled():
            self.page.primary()

    def _stop(self) -> None:
        if self.page is not None:
            self.page.stop()


__all__ = ["MainToolBar"]
