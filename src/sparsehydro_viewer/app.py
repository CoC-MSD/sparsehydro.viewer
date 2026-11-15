"""QApplication setup."""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QCoreApplication, QSettings
from PySide6.QtWidgets import QApplication

from . import APP_NAME, ORG_NAME, __version__, theme


def create_app(argv: list[str] | None = None) -> QApplication:
    QCoreApplication.setOrganizationName(ORG_NAME)
    QCoreApplication.setApplicationName(APP_NAME)
    QCoreApplication.setApplicationVersion(__version__)
    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv[:1])
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
