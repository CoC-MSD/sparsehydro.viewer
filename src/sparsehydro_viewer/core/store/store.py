"""Typed access to a project database.

The application edits an in-memory working copy (:meth:`ProjectStore.open`
copies the file into memory) and :meth:`ProjectStore.save_to` writes it back
with SQLite's backup API, so "unsaved changes" behave as in any desktop
application and a crash never leaves a half-written project file.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .arrays import pack, pack_time, unpack, unpack_time
from .schema import APPLICATION_ID, ATTRIBUTE_DEFINITIONS, DDL, OBSERVED_PROPERTIES, SCHEMA_VERSION, WSYS

CLIENT = "local"

#: ``class_iri`` of each node table.
CLASS_IRI = {
    "monitoring_site": WSYS + "MonitoringSite",
    "sensor": WSYS + "Sensor",
    "zone": WSYS + "Zone",
}
KIND_PREFIX = {"monitoring_site": "site", "sensor": "sensor", "zone": "zone", "datastream": "stream",
               "incident": "incident"}
SENSOR_KINDS = ("FLOW_METER", "RAIN_GAGE", "LEVEL_SENSOR", "VELOCITY_SENSOR", "TEMPERATURE_SENSOR", "VIRTUAL")


class StoreError(Exception):
    """A project file cannot be opened or is inconsistent."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _slug(text: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", text.strip()).strip("-").lower()
    return s[:40] or "node"


def new_iri(kind: str, label: str = "") -> str:
    """``wsys:<kind>/local/<slug>-<id>`` (ontology IRI pattern; ``local`` stands for the client)."""
    return f"wsys:{KIND_PREFIX.get(kind, kind)}/{CLIENT}/{_slug(label)}-{uuid.uuid4().hex[:6]}"


@dataclass
class Node:
    """A row of ``monitoring_site``, ``sensor`` or ``zone``."""

    iri: str
    table: str
    label: str = ""
    description: str = ""
    geometry: str | None = None
    alt_ids: list[str] = field(default_factory=list)
    source_system: str = ""
    extra: dict[str, Any] = field(default_factory=dict)  # class-specific columns (e.g. sensor_kind)

    @property
    def class_iri(self) -> str:
        return CLASS_IRI[self.table]


@dataclass(frozen=True)
class AttributeDefinition:
    key: str
    label: str
    value_type: str
    unit: str = ""
    category: str = "Attributes"
    minimum: float | None = None
    maximum: float | None = None
    decimals: int | None = None
    choices: tuple[str, ...] = ()
    description: str = ""
    applies_to: tuple[str, ...] = ()
    ontology_slot: bool = False


_NODE_COLUMNS = ("iri", "class_iri", "label", "description", "alt_ids", "source_system", "geometry")
_EXTRA_COLUMNS = {
    "monitoring_site": ("system",),
    "sensor": ("sensor_kind", "lifecycle_status", "sampling_interval", "manufacturer", "model_number",
               "serial_number"),
    "zone": ("zone_kind", "zone_basis", "zone_code"),
}


class ProjectStore:
    """Connection to a project database (usually an in-memory working copy)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    # ------------------------------------------------------------------ lifecycle

    @classmethod
    def memory(cls) -> ProjectStore:
        """A new, empty project."""
        store = cls(sqlite3.connect(":memory:", check_same_thread=False))
        store._initialise()
        return store

    @classmethod
    def open(cls, path: str | Path) -> ProjectStore:
        """Copy the project file at *path* into a new in-memory working copy."""
        path = Path(path)
        if not path.is_file():
            raise StoreError(f"{path} does not exist")
        src = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            app_id = src.execute("PRAGMA application_id").fetchone()[0]
            version = src.execute("PRAGMA user_version").fetchone()[0]
            if app_id != APPLICATION_ID:
                raise StoreError(f"{path.name} is not a sparsehydro-viewer project file")
            if version > SCHEMA_VERSION:
                raise StoreError(f"{path.name} was written by a newer sparsehydro-viewer (schema {version})")
            mem = sqlite3.connect(":memory:", check_same_thread=False)
            src.backup(mem)
        finally:
            src.close()
        store = cls(mem)
        store._migrate(version)
        return store

    def save_to(self, path: str | Path) -> None:
        """Write the working copy to *path* (atomically: written beside it, then renamed)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        if tmp.exists():
            tmp.unlink()
        dest = sqlite3.connect(tmp)
        try:
            self.conn.commit()
            self.conn.backup(dest)
        finally:
            dest.close()
        tmp.replace(path)

    def close(self) -> None:
        self.conn.close()

    def _initialise(self) -> None:
        with self.transaction() as c:
            c.executescript(DDL)
            c.execute(f"PRAGMA application_id = {APPLICATION_ID}")
            c.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            c.execute("INSERT OR REPLACE INTO meta VALUES ('created', ?)", (_now(),))
            c.executemany("INSERT OR IGNORE INTO observed_property VALUES (?, ?, ?, ?)", OBSERVED_PROPERTIES)
            self._seed_definitions(c)

    def _seed_definitions(self, c) -> None:
        """Add the built-in attribute definitions a project does not have yet (user edits are kept)."""
        have = {r[0] for r in c.execute("SELECT key FROM attribute_definition")}
        for d in ATTRIBUTE_DEFINITIONS:
            if d[0] not in have:
                self._insert_definition(c, AttributeDefinition(d[0], d[1], d[2], d[3], d[4], d[5], d[6], d[7],
                                                               tuple(d[8]), d[9], tuple(d[10]), bool(d[11])))

    def _migrate(self, version: int) -> None:
        if version < SCHEMA_VERSION:  # future migrations go here, one step per version
            raise StoreError(f"cannot upgrade schema version {version}")
        with self.transaction() as c:  # idempotent: adds tables/views introduced without a version bump
            c.executescript(DDL)
            self._seed_definitions(c)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    # ------------------------------------------------------------------ nodes

    def add_node(self, table: str, label: str, *, description: str = "", geometry: str | None = None,
                 alt_ids: list[str] | None = None, source_system: str = "", iri: str | None = None,
                 **extra: Any) -> str:
        if table not in CLASS_IRI:
            raise ValueError(f"unknown node table {table!r}")
        iri = iri or new_iri(table, label)
        cols = list(_NODE_COLUMNS) + [k for k in extra if k in _EXTRA_COLUMNS[table]]
        vals = [iri, CLASS_IRI[table], label, description, json.dumps(alt_ids or []), source_system, geometry]
        vals += [extra[k] for k in cols[len(_NODE_COLUMNS):]]
        with self.transaction() as c:
            c.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", vals)
        return iri

    def add_site(self, label: str, **kw: Any) -> str:
        return self.add_node("monitoring_site", label, **kw)

    def add_sensor(self, site_iri: str, sensor_kind: str, label: str = "", **kw: Any) -> str:
        if sensor_kind not in SENSOR_KINDS:
            raise ValueError(f"sensor_kind must be one of {SENSOR_KINDS}")
        iri = self.add_node("sensor", label or sensor_kind.replace("_", " ").lower(), sensor_kind=sensor_kind, **kw)
        self.add_edge(iri, site_iri, "ATTACHED_TO")
        return iri

    def node(self, iri: str) -> Node | None:
        for table in CLASS_IRI:
            row = self.conn.execute(f"SELECT * FROM {table} WHERE iri = ?", (iri,)).fetchone()
            if row is not None:
                return self._node(table, row)
        return None

    def nodes(self, table: str | None = None) -> list[Node]:
        tables = [table] if table else list(CLASS_IRI)
        out = []
        for t in tables:
            for row in self.conn.execute(f"SELECT * FROM {t} ORDER BY label, iri"):
                out.append(self._node(t, row))
        return out

    @staticmethod
    def _node(table: str, row: sqlite3.Row) -> Node:
        extra = {k: row[k] for k in _EXTRA_COLUMNS[table]}
        return Node(row["iri"], table, row["label"], row["description"], row["geometry"],
                    json.loads(row["alt_ids"] or "[]"), row["source_system"], extra)

    def update_node(self, iri: str, **fields: Any) -> None:
        node = self.node(iri)
        if node is None:
            raise KeyError(iri)
        allowed = {"label", "description", "geometry", "source_system", "alt_ids", *_EXTRA_COLUMNS[node.table]}
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"cannot update {sorted(unknown)} on {node.table}")
        if "alt_ids" in fields:
            fields["alt_ids"] = json.dumps(list(fields["alt_ids"]))
        if fields:
            sets = ", ".join(f"{k} = ?" for k in fields)
            with self.transaction() as c:
                c.execute(f"UPDATE {node.table} SET {sets} WHERE iri = ?", [*fields.values(), iri])

    def delete_node(self, iri: str) -> None:
        """Delete a node with its edges, attributes and the datastreams observing it or recorded by it."""
        node = self.node(iri)
        if node is None:
            return
        with self.transaction() as c:
            streams = [r[0] for r in c.execute(
                "SELECT iri FROM datastream WHERE feature_of_interest = ? OR sensor = ?", (iri, iri))]
            for s in streams:
                c.execute("DELETE FROM observation_array WHERE datastream = ?", (s,))
                c.execute("DELETE FROM datastream WHERE iri = ?", (s,))
            c.execute("DELETE FROM edge WHERE from_iri = ? OR to_iri = ?", (iri, iri))
            c.execute("DELETE FROM attribute_measurement WHERE feature_of_interest = ?", (iri,))
            c.execute(f"DELETE FROM {node.table} WHERE iri = ?", (iri,))

    # ------------------------------------------------------------------ edges

    def add_edge(self, from_iri: str, to_iri: str, relation: str, props: dict | None = None) -> None:
        with self.transaction() as c:
            c.execute("INSERT OR REPLACE INTO edge (from_iri, to_iri, relation, props) VALUES (?, ?, ?, ?)",
                      (from_iri, to_iri, relation, json.dumps(props or {})))

    def edges(self, *, from_iri: str | None = None, to_iri: str | None = None,
              relation: str | None = None) -> list[tuple[str, str, str]]:
        q, args = "SELECT from_iri, to_iri, relation FROM edge WHERE 1=1", []
        for col, val in (("from_iri", from_iri), ("to_iri", to_iri), ("relation", relation)):
            if val is not None:
                q += f" AND {col} = ?"
                args.append(val)
        return [tuple(r) for r in self.conn.execute(q, args)]

    def sensors_of(self, site_iri: str) -> list[Node]:
        return [n for (s, _, _) in self.edges(to_iri=site_iri, relation="ATTACHED_TO")
                if (n := self.node(s)) is not None and n.table == "sensor"]

    # ------------------------------------------------------------------ time series

    def add_datastream(self, sensor_iri: str, observed_property: str, feature_of_interest: str,
                       label: str = "", stream_role: str = "RAW") -> str:
        iri = new_iri("datastream", label or observed_property.rsplit("/", 1)[-1])
        with self.transaction() as c:
            c.execute("INSERT INTO datastream (iri, label, sensor, observed_property, feature_of_interest, "
                      "stream_role) VALUES (?, ?, ?, ?, ?, ?)",
                      (iri, label, sensor_iri, observed_property, feature_of_interest, stream_role))
        return iri

    def datastreams(self, feature_of_interest: str | None = None) -> list[dict[str, Any]]:
        q = "SELECT * FROM datastream" + (" WHERE feature_of_interest = ?" if feature_of_interest else "")
        rows = self.conn.execute(q, (feature_of_interest,) if feature_of_interest else ())
        return [dict(r) for r in rows]

    def write_series(self, datastream: str, times: np.ndarray, values: np.ndarray, unit: str, *,
                     result_kind: str = "MEASUREMENT", was_generated_by: str = "") -> None:
        values = np.asarray(values, dtype=float)
        if len(values) != len(times):
            raise ValueError("times and values differ in length")
        start, step, count, packed_t = pack_time(np.asarray(times))
        with self.transaction() as c:
            c.execute('INSERT OR REPLACE INTO observation_array (datastream, result_kind, start_ns, step_ns, count, '
                      'times, "values", unit, was_generated_by, result_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                      (datastream, result_kind, start, step, count, packed_t, pack(values), unit,
                       was_generated_by, _now()))

    def read_series(self, datastream: str, result_kind: str = "MEASUREMENT") -> pd.Series | None:
        row = self.conn.execute("SELECT * FROM observation_array WHERE datastream = ? AND result_kind = ?",
                                (datastream, result_kind)).fetchone()
        if row is None:
            return None
        t = unpack_time(row["start_ns"], row["step_ns"], row["count"], row["times"])
        return pd.Series(unpack(row["values"]), index=pd.DatetimeIndex(t, name="datetime"), name=datastream)

    def series_unit(self, datastream: str) -> str | None:
        row = self.conn.execute("SELECT unit FROM observation_array WHERE datastream = ?", (datastream,)).fetchone()
        return None if row is None else row[0]

    # ------------------------------------------------------------------ attributes

    @staticmethod
    def _insert_definition(c: sqlite3.Connection, d: AttributeDefinition) -> None:
        c.execute("INSERT OR REPLACE INTO attribute_definition VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  (d.key, d.label, d.value_type, d.unit, d.category, d.minimum, d.maximum, d.decimals,
                   json.dumps(list(d.choices)), d.description, json.dumps(list(d.applies_to)), int(d.ontology_slot)))

    def define_attribute(self, d: AttributeDefinition) -> None:
        """Add or replace an attribute definition (custom keys should start with ``shv:``)."""
        if d.value_type not in ("float", "int", "str", "bool", "choice", "datetime"):
            raise ValueError(f"unsupported value type {d.value_type!r}")
        with self.transaction() as c:
            self._insert_definition(c, d)

    def attribute_definitions(self) -> list[AttributeDefinition]:
        out = []
        for r in self.conn.execute("SELECT * FROM attribute_definition ORDER BY category, label"):
            out.append(AttributeDefinition(r["key"], r["label"], r["value_type"], r["unit"], r["category"],
                                           r["minimum"], r["maximum"], r["decimals"],
                                           tuple(json.loads(r["choices"])), r["description"],
                                           tuple(json.loads(r["applies_to"])), bool(r["ontology_slot"])))
        return out

    def definition(self, key: str) -> AttributeDefinition | None:
        return next((d for d in self.attribute_definitions() if d.key == key), None)

    def set_attribute(self, iri: str, key: str, value: Any, *, source: str = "MANUAL") -> None:
        """Set (or with ``None`` clear) attribute *key* of node *iri*."""
        d = self.definition(key)
        if d is None:
            raise KeyError(f"attribute {key!r} is not defined")
        with self.transaction() as c:
            if value is None:
                c.execute("DELETE FROM attribute_measurement WHERE feature_of_interest = ? AND attribute = ?",
                          (iri, key))
                return
            num, text = None, None
            if d.value_type in ("float", "int"):
                num = float(value)
            elif d.value_type == "bool":
                num = 1.0 if value else 0.0
            else:
                text = str(value)
            c.execute("INSERT INTO attribute_measurement (feature_of_interest, attribute, measured_value, "
                      "measured_text, measured_unit, measurement_source, phenomenon_time) VALUES (?, ?, ?, ?, ?, ?, ?) "
                      "ON CONFLICT (feature_of_interest, attribute) DO UPDATE SET measured_value = excluded.measured_value, "
                      "measured_text = excluded.measured_text, measured_unit = excluded.measured_unit, "
                      "measurement_source = excluded.measurement_source, phenomenon_time = excluded.phenomenon_time",
                      (iri, key, num, text, d.unit, source, _now()))

    def attributes(self, iri: str) -> dict[str, Any]:
        defs = {d.key: d for d in self.attribute_definitions()}
        out: dict[str, Any] = {}
        for r in self.conn.execute("SELECT attribute, measured_value, measured_text FROM attribute_measurement "
                                   "WHERE feature_of_interest = ?", (iri,)):
            d = defs.get(r["attribute"])
            if d is None:
                continue
            if d.value_type == "int":
                out[d.key] = int(r["measured_value"])
            elif d.value_type == "float":
                out[d.key] = float(r["measured_value"])
            elif d.value_type == "bool":
                out[d.key] = bool(r["measured_value"])
            else:
                out[d.key] = r["measured_text"]
        return out

    # ------------------------------------------------------------------ project-level records (viewer extension)

    def set_setting(self, key: str, value: Any) -> None:
        with self.transaction() as c:
            c.execute("INSERT OR REPLACE INTO setting VALUES (?, ?)", (key, json.dumps(value, default=str)))

    def setting(self, key: str, default: Any = None) -> Any:
        row = self.conn.execute("SELECT value FROM setting WHERE key = ?", (key,)).fetchone()
        return default if row is None else json.loads(row[0])

    def replace_rows(self, table: str, rows: list[tuple]) -> None:
        """Replace the whole content of a viewer table (``site_dataset``, ``model_spec``, ``run``...)."""
        if table not in ("site_dataset", "model_spec", "run", "run_array", "event_group"):
            raise ValueError(table)
        with self.transaction() as c:
            c.execute(f"DELETE FROM {table}")
            if rows:
                c.executemany(f"INSERT INTO {table} VALUES ({', '.join('?' * len(rows[0]))})", rows)

    def rows(self, table: str, order: str = "rowid") -> list[sqlite3.Row]:
        return list(self.conn.execute(f"SELECT * FROM {table} ORDER BY {order}"))

    # ------------------------------------------------------------------ helpers for datasets

    def import_frame(self, name: str, frame: pd.DataFrame, *, source_system: str = "",
                     site_iri: str | None = None) -> dict[str, str]:
        """Create (or reuse) a site with rain gauge and flow meter sensors and store the frame's series.

        :returns: ``{"site": iri, "rain": stream iri, "flow": stream iri[, "temperature": ...]}``.
        """
        t = frame["datetime"].to_numpy()
        site = site_iri or self.add_site(name, source_system=source_system)
        out = {"site": site}
        specs = [("rain", "RAIN_GAGE", "wsys:prop/rainfall_depth", "unit:IN"),
                 ("stormflow", "FLOW_METER", "wsys:prop/flow", "unit:FT3-PER-SEC")]
        if "temperature_c" in frame.columns:
            specs.append(("temperature_c", "TEMPERATURE_SENSOR", "wsys:prop/temperature", "unit:DEG_C"))
        existing = {n.extra.get("sensor_kind"): n.iri for n in self.sensors_of(site)}
        for col, kind, prop, unit in specs:
            sensor = existing.get(kind) or self.add_sensor(site, kind, source_system=source_system)
            stream = self.add_datastream(sensor, prop, site, label=f"{name} {col}")
            self.write_series(stream, t, frame[col].to_numpy(dtype=float), unit)
            out["temperature" if col == "temperature_c" else ("rain" if col == "rain" else "flow")] = stream
        return out

    def frame(self, rain: str, flow: str, temperature: str | None = None) -> pd.DataFrame:
        """Rebuild the standard frame (``datetime``, ``rain``, ``stormflow``[, ``temperature_c``])."""
        r, q = self.read_series(rain), self.read_series(flow)
        if r is None or q is None:
            raise StoreError("dataset series are missing from the project")
        df = pd.concat([r.rename("rain"), q.rename("stormflow")], axis=1, join="inner")
        if temperature:
            temp = self.read_series(temperature)
            if temp is not None:
                df = df.join(temp.rename("temperature_c"), how="left")
        return df.reset_index()


__all__ = ["CLASS_IRI", "SENSOR_KINDS", "AttributeDefinition", "Node", "ProjectStore", "StoreError", "new_iri"]
