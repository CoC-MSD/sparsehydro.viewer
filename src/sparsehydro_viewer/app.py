"""QApplication setup."""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QCoreApplication, QSettings
from PySide6.QtWidgets import QApplication

from . import APP_NAME, ORG_NAME, __version__, theme
from .platform import APP_USER_MODEL_ID  # noqa: E402


def _windows_taskbar_identity() -> None:
    """Group the windows under the application's own taskbar icon rather than python.exe's."""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        except (AttributeError, OSError):
            pass


def _load_user_extensions() -> None:
    """Import extension modules listed in the settings (``extensions/modules``) and rediscover components."""
    raw = QSettings().value("extensions/modules", "")
    targets = [t for t in (raw if isinstance(raw, list) else str(raw or "").splitlines()) if str(t).strip()]
    if not targets:
        return
    from .core import components
    from .core.extensions import load_extensions
    from .core.objectives import OBJECTIVES

    rep = load_extensions(targets)
    for label, err in rep.failed:
        logging.getLogger(__name__).warning("extension %s failed to load: %s", label, err)
    components.refresh()
    OBJECTIVES.refresh()


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
    _load_user_extensions()
    wanted = theme.by_name(QSettings().value("theme", "light"))
    if created or theme.current() is not wanted:  # re-applying restyles every existing widget
        theme.apply(app, wanted)
    return app


def run(project: str | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    app = create_app()
    from .views.main_window import MainWindow

    win = MainWindow()
    win.show()
    from .platform import apply_taskbar_identity

    apply_taskbar_identity(win)  # taskbar icon and relaunch command when started from Python
    if project:
        win.open_project(project, confirm=False)
    return app.exec()
