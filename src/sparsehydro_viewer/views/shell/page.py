"""Base class for workspace pages.

A page tells the application shell what to show in the standard toolbar and
status bar:

* ``primary_text`` / :meth:`primary` - the page's main command (Run button);
* :meth:`stop` / :meth:`stop_enabled` - cancel what the page started (Stop);
* :meth:`context_actions` - page-specific toolbar buttons;
* :meth:`active_chart` - the chart the shared navigation buttons act on;
* :meth:`status_text` - page-specific text for the status bar's context zone.

A page that shows the working model (its hydrograph, its point in a Pareto
plot, its row in a table) calls :meth:`Page.watch_working_model` and
implements :meth:`Page.working_model_changed`: the visible page is redrawn
with every evaluation (every slider move), a hidden one when it is next shown.

Pages emit :attr:`contextChanged` whenever any of these change; the shell
re-reads them.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QWidget

from ...resources import icon
from ...widgets.timeseries_plot import TimeseriesPlot
from ..context import AppContext


class Page(QWidget):
    title = ""
    icon_name = ""
    uses_working_model = False
    primary_text = ""  # empty: the page has no Run command
    primary_tip = ""

    contextChanged = Signal()

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self._job_ids: set[int] = set()
        self._working_stale = False
        ctx.jobs.jobChanged.connect(self._job_changed)

    # -- the working model on this page -----------------------------------------

    def watch_working_model(self) -> None:
        """Call :meth:`working_model_changed` whenever the working model is re-evaluated or renamed."""
        c = self.ctx.controller
        c.result.connect(self._working_result)
        c.unavailable.connect(lambda *_: self._working_result(None))
        self.ctx.session.modelRenamed.connect(lambda: self._working_result(c.last))

    def _working_result(self, res) -> None:
        if self.isVisible():
            self._working_stale = False
            self.working_model_changed(res)
        else:
            self._working_stale = True  # redrawn when the page is shown

    def working_model_changed(self, res) -> None:
        """Redraw what this page shows of the working model.

        :param res: The latest :class:`~sparsehydro_viewer.services.LiveResult`, or ``None`` when the working
            model cannot be evaluated (no dataset, or the evaluation failed).
        """

    def showEvent(self, ev) -> None:  # noqa: N802 (Qt naming)
        super().showEvent(ev)
        if self._working_stale:
            self._working_stale = False
            self.working_model_changed(self.ctx.controller.last)

    # -- shell protocol ----------------------------------------------------

    def primary(self) -> None:
        """Run the page's main command."""

    def primary_enabled(self) -> bool:
        return bool(self.primary_text)

    def stop(self) -> None:
        """Cancel what this page started (background jobs by default)."""
        for job_id in list(self._job_ids):
            self.ctx.jobs.cancel(job_id)

    def stop_enabled(self) -> bool:
        return bool(self._job_ids)

    def context_actions(self) -> list[QAction | None]:
        """Page-specific toolbar actions; ``None`` inserts a separator."""
        return []

    def active_chart(self) -> TimeseriesPlot | None:
        return None

    def status_text(self) -> str:
        return ""

    # -- helpers for subclasses -------------------------------------------------

    def action(self, text: str, tip: str, icon_name: str, slot=None, *, shortcut: str | None = None,
               checkable: bool = False, color: str | None = None) -> QAction:
        """Create a toolbar action owned by this page."""
        act = QAction(icon(icon_name, color), text, self)
        act.setToolTip(f"{tip}  [{shortcut}]" if shortcut else tip)
        act.setStatusTip(tip)
        act.setCheckable(checkable)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
        if slot is not None:
            act.triggered.connect(lambda *_: slot())
        return act

    def submit_job(self, label: str, fn, *, on_done=None, on_error=None):
        """Submit a background job that the toolbar's Stop button can cancel."""
        job = self.ctx.jobs.submit(label, fn, on_done=on_done, on_error=on_error)
        self._job_ids.add(job.info.id)
        self.contextChanged.emit()
        return job

    def _job_changed(self, job_id: int) -> None:
        if job_id in self._job_ids and self.ctx.jobs.info(job_id).state != "running":
            self._job_ids.discard(job_id)
            self.contextChanged.emit()


__all__ = ["Page"]
