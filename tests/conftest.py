"""Shared fixtures.

``tests/data/tc-nb-001_2022-05.csv`` is three weeks (May 2022, 5-minute) of the
TC-NB-001 rain/stormflow series distributed with sparsehydro.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

DATA = Path(__file__).parent / "data"
SAMPLE_CSV = DATA / "tc-nb-001_2022-05.csv"


@pytest.fixture(scope="session")
def sample_csv() -> Path:
    return SAMPLE_CSV


@pytest.fixture(scope="session")
def sample_frame() -> pd.DataFrame:
    from sparsehydro_viewer.core.data import DatasetSpec, load_dataset

    return load_dataset(DatasetSpec("sample", path=str(SAMPLE_CSV)))


@pytest.fixture(autouse=True)
def _delete_closed_windows():
    """Delete the main windows a test closed. Closed windows otherwise stay alive (with their timers and
    widgets) for the whole session, and every later test gets slower."""
    yield
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication, QMainWindow

    app = QApplication.instance()
    if app is None:
        return
    closed = [w for w in app.topLevelWidgets() if isinstance(w, QMainWindow) and not w.isVisible()]
    for w in closed:
        w.deleteLater()
    if closed:
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture
def short_frame(sample_frame: pd.DataFrame) -> pd.DataFrame:
    """First week only, for fast evaluator tests."""
    return sample_frame.iloc[: 7 * 288].reset_index(drop=True)
