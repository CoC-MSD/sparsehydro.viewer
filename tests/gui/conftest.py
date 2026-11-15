from __future__ import annotations

import pytest
from PySide6.QtCore import QCoreApplication, QSettings


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, qapp):
    """Keep QSettings (recent files, window state, theme) out of the user's real settings."""
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    QCoreApplication.setOrganizationName("sparsehydro-tests")
    QCoreApplication.setApplicationName("viewer-tests")
    yield
