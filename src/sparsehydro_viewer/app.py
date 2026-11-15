"""QApplication setup."""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QCoreApplication, QSettings
from PySide6.QtWidgets import QApplication

from . import APP_NAME, ORG_NAME, __version__, theme

APP_USER_MODEL_ID = "sparsehydro.viewer"


def _windows_taskbar_identity() -> None:
    """Group the windows under the application's own taskbar icon rather than python.exe's."""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        except (AttributeError, OSError):
            pass


def create_app(argv: list[str] | None = None) -> QApplication:
    QCoreApplication.setOrganizationName(ORG_NAME)
    QCoreApplication.setApplicationName(APP_NAME)
    QCoreApplication.setApplicationVersion(__version__)
    created = QApplication.instance() is None
    if created:
        _windows_taskbar_identity()
    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv[:1])
    if app.windowIcon().isNull():
        from .resources import app_icon

        app.setWindowIcon(app_icon())
    name = QSettings().value("theme", "light")
    theme.apply(app, theme.DARK if name == "dark" else theme.LIGHT)
    return app


def run(project: str | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    app = create_app()
    from .views.main_window import MainWindow

    win = MainWindow()
    win.show()
    if project:
        win.open_project(project, confirm=False)
    return app.exec()
