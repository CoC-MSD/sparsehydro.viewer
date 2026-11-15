from __future__ import annotations

import sqlite3
import time

import numpy as np
import pandas as pd
import pytest

from sparsehydro_viewer.core.store import AttributeDefinition, ProjectStore, StoreError
from sparsehydro_viewer.core.store.arrays import pack, pack_time, unpack, unpack_time


def test_arrays_round_trip_exactly() -> None:
    v = np.random.default_rng(1).normal(size=1000)
    assert np.array_equal(unpack(pack(v)), v)
    regular = pd.date_range("2022-01-01", periods=500, freq="5min").to_numpy()
    start, step, n, blob = pack_time(regular)
    assert step == 300 * 10**9 and blob is None
    assert np.array_equal(unpack_time(start, step, n, blob), regular)
    irregular = np.delete(regular, [10, 11, 200])
    start, step, n, blob = pack_time(irregular)
    assert step is None and blob is not None
    assert np.array_equal(unpack_time(start, step, n, blob), irregular)


def test_nodes_edges_attributes_and_save(tmp_path, sample_frame) -> None:
    st = ProjectStore.memory()
    site = st.add_site("MH-12", description="Manhole 12", geometry="POINT (-84.51 39.10)", alt_ids=["flowiq:12"])
    zone = st.add_node("zone", "Sewershed A", geometry="POLYGON ((-84.6 39.0, -84.4 39.0, -84.4 39.2, -84.6 39.0))")
    st.add_edge(site, zone, "BELONGS_TO_ZONE")
    ids = st.import_frame("MH-12", sample_frame, site_iri=site)
    assert st.node(site).geometry == "POINT (-84.51 39.10)" and st.node(site).alt_ids == ["flowiq:12"]
    assert {n.extra["sensor_kind"] for n in st.sensors_of(site)} == {"RAIN_GAGE", "FLOW_METER"}
    st.set_attribute(site, "shv:contributing_area", 42.5)
    st.set_attribute(site, "vertical_datum", "NAVD88")
    st.define_attribute(AttributeDefinition("shv:owner", "Owner", "str", category="Admin"))
    st.set_attribute(site, "shv:owner", "MSD")
    with pytest.raises(KeyError):
        st.set_attribute(site, "shv:undefined", 1)

    path = tmp_path / "p.shproj"
    st.save_to(path)
    back = ProjectStore.open(path)
    assert back.attributes(site) == {"shv:contributing_area": 42.5, "vertical_datum": "NAVD88", "shv:owner": "MSD"}
    assert back.edges(from_iri=site, relation="BELONGS_TO_ZONE") == [(site, zone, "BELONGS_TO_ZONE")]
    frame = back.frame(ids["rain"], ids["flow"])
    pd.testing.assert_frame_equal(frame, sample_frame[["datetime", "rain", "stormflow"]], check_names=False)
    assert back.series_unit(ids["flow"]) == "unit:FT3-PER-SEC"

    back.delete_node(site)
    assert back.node(site) is None and back.attributes(site) == {} and back.datastreams(site) == []
    assert back.edges(to_iri=zone) == []


def test_working_copy_is_independent_of_the_file(tmp_path) -> None:
    st = ProjectStore.memory()
    a = st.add_site("A")
    path = tmp_path / "x.shproj"
    st.save_to(path)
    work = ProjectStore.open(path)
    work.add_site("B")
    assert len(ProjectStore.open(path).nodes("monitoring_site")) == 1  # file untouched until saved
    work.update_node(a, label="A renamed")
    work.save_to(path)
    assert {n.label for n in ProjectStore.open(path).nodes()} == {"A renamed", "B"}


def test_rejects_foreign_and_newer_files(tmp_path) -> None:
    other = tmp_path / "other.shproj"
    sqlite3.connect(other).close()
    with pytest.raises(StoreError, match="not a sparsehydro-viewer project"):
        ProjectStore.open(other)
    st = ProjectStore.memory()
    newer = tmp_path / "newer.shproj"
    st.save_to(newer)
    c = sqlite3.connect(newer)
    c.execute("PRAGMA user_version = 99")
    c.commit()
    c.close()
    with pytest.raises(StoreError, match="newer"):
        ProjectStore.open(newer)


def test_long_record_is_compact_and_fast(tmp_path) -> None:
    """Five years of 5-minute data: small file, fast load."""
    n = 5 * 365 * 288
    t = pd.date_range("2018-01-01", periods=n, freq="5min")
    rng = np.random.default_rng(0)
    frame = pd.DataFrame({"datetime": t, "rain": np.round(rng.exponential(0.01, n) * (rng.random(n) < 0.05), 2),
                          "stormflow": np.round(rng.gamma(2.0, 0.3, n), 3)})
    st = ProjectStore.memory()
    ids = st.import_frame("long", frame)
    path = tmp_path / "long.shproj"
    st.save_to(path)
    t0 = time.perf_counter()
    back = ProjectStore.open(path)
    df = back.frame(ids["rain"], ids["flow"])
    elapsed = time.perf_counter() - t0
    assert len(df) == n and elapsed < 2.0, elapsed
    assert path.stat().st_size < 12_000_000
