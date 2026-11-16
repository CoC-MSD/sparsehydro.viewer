"""Which rain gauge and temperature series a dataset uses, and changing them."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from sparsehydro_viewer.core.data import DatasetSpec
from sparsehydro_viewer.core.project import PROP_RAIN, PROP_TEMPERATURE, Project


@pytest.fixture
def project(short_frame) -> Project:
    """Site A (rain, flow) and gauge site B with twice the rain and a temperature series."""
    proj = Project()
    proj.add_dataset(DatasetSpec("A"), short_frame)
    other = short_frame.assign(rain=short_frame["rain"] * 2.0, temperature_c=12.5)
    proj.add_dataset(DatasetSpec("B"), other)
    return proj


def test_catalog_lists_series_with_site_span_and_step(project) -> None:
    rain = project.store.series_catalog(PROP_RAIN)
    assert sorted(e["site_label"] for e in rain) == ["A", "B"]
    e = rain[0]
    assert e["step_minutes"] == 5.0 and e["count"] == 7 * 288 and e["end"] > e["start"]
    assert [e["site_label"] for e in project.store.series_catalog(PROP_TEMPERATURE)] == ["B"]
    assert len(project.store.series_catalog()) == 5  # two rain, two flow, one temperature


def test_inputs_are_named(project) -> None:
    inputs = project.dataset_inputs("A")
    assert inputs["rain"]["site_label"] == "A" and inputs["temperature"] is None
    assert project.inputs_text("A") == "rain: A rain; temperature: none"
    assert project.inputs_text("nope") == ""


def test_another_sites_gauge_changes_the_frame_and_links_the_sites(project) -> None:
    a, b = project.dataset("A"), project.dataset("B")
    before = project.frame("A")
    project.set_dataset_inputs("A", rain_stream=b.rain_stream, temperature_stream=b.temperature_stream)
    after = project.frame("A")
    np.testing.assert_allclose(after["rain"], before["rain"] * 2.0)
    np.testing.assert_allclose(after["stormflow"], before["stormflow"])  # still its own flow
    np.testing.assert_allclose(after["temperature_c"], 12.5)
    assert project.inputs_text("A") == "rain: B rain @ B; temperature: B temperature_c @ B"
    assert project.store.edges(from_iri=a.site_iri, relation="USES_GAGE") == [(a.site_iri, b.site_iri, "USES_GAGE")]
    # Back to its own gauge and no temperature: the link goes.
    own = next(e["iri"] for e in project.store.series_catalog(PROP_RAIN) if e["site_iri"] == a.site_iri)
    project.set_dataset_inputs("A", rain_stream=own, temperature_stream=None)
    assert project.store.edges(from_iri=a.site_iri, relation="USES_GAGE") == []
    assert "temperature_c" not in project.frame("A").columns


def test_only_the_named_input_changes(project) -> None:
    a, b = project.dataset("A"), project.dataset("B")
    rain = a.rain_stream
    project.set_dataset_inputs("A", temperature_stream=b.temperature_stream)
    assert a.rain_stream == rain and a.temperature_stream == b.temperature_stream


def test_wrong_kind_and_non_overlapping_series_are_refused(project, short_frame) -> None:
    a, b = project.dataset("A"), project.dataset("B")
    rain = a.rain_stream
    with pytest.raises(ValueError, match="not a rain series"):
        project.set_dataset_inputs("A", rain_stream=b.temperature_stream)
    with pytest.raises(ValueError, match="not a temperature series"):
        project.set_dataset_inputs("A", temperature_stream=b.rain_stream)
    later = short_frame.assign(datetime=short_frame["datetime"] + pd.Timedelta(days=400))
    project.add_dataset(DatasetSpec("C"), later)
    with pytest.raises(ValueError, match="do not overlap"):
        project.set_dataset_inputs("A", rain_stream=project.dataset("C").rain_stream)
    assert a.rain_stream == rain  # unchanged after a refusal
