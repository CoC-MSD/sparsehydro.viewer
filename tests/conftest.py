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


@pytest.fixture
def short_frame(sample_frame: pd.DataFrame) -> pd.DataFrame:
    """First week only, for fast evaluator tests."""
    return sample_frame.iloc[: 7 * 288].reset_index(drop=True)
