"""SQLite schema of a project file (``*.shproj``).

Tables named after water-ontology classes (``water-ontology/schema``, LinkML,
``wsys:`` namespace) use the ontology's slot names, so rows can be exported to
ontology rows unchanged:

=========================  =====================  =====================================
table                      ontology class         notes
=========================  =====================  =====================================
``monitoring_site``        MonitoringSite         the general "node": flow meter site,
                                                  rain gauge site, any monitored place
``sensor``                 Sensor                 ``sensor_kind`` FLOW_METER, RAIN_GAGE...
``zone``                   Zone                   sewersheds, drainage areas (polygons)
``edge``                   Edge                   ATTACHED_TO, BELONGS_TO_ZONE, USES_GAGE...
``observed_property``      ObservedProperty       flow, rainfall depth, temperature...
``datastream``             Datastream             time-series header
``observation_array``      Observation (packed)   one row per datastream and result kind
``attribute_measurement``  AttributeMeasurement   optional attributes, current values
``incident``               Incident               storm events (``incident_type`` STORM)
=========================  =====================  =====================================

Locations are ``geometry`` in WKT, EPSG:4326 (ontology convention).  Tables
the ontology does not cover are viewer extensions: ``attribute_definition``
(custom keys are namespaced ``shv:`` and not exported), ``site_dataset``,
``model_spec``, ``run``, ``run_array``, ``event_group``, ``setting``,
``meta``.
"""

from __future__ import annotations

#: ``PRAGMA application_id`` of project files ("SHPJ").
APPLICATION_ID = 0x53485044
#: ``PRAGMA user_version`` written by this code; older files are migrated on open.
SCHEMA_VERSION = 1

_ENTITY = """
    iri            TEXT PRIMARY KEY,
    class_iri      TEXT NOT NULL,
    label          TEXT NOT NULL DEFAULT '',
    description    TEXT NOT NULL DEFAULT '',
    alt_ids        TEXT NOT NULL DEFAULT '[]',
    source_system  TEXT NOT NULL DEFAULT '',
    geometry       TEXT,
    valid_from     TEXT,
    valid_to       TEXT
"""

DDL = f"""
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS monitoring_site ({_ENTITY},
    system TEXT
);
CREATE TABLE IF NOT EXISTS sensor ({_ENTITY},
    sensor_kind        TEXT NOT NULL,
    lifecycle_status   TEXT NOT NULL DEFAULT 'IN_SERVICE',
    sampling_interval  TEXT,
    manufacturer       TEXT,
    model_number       TEXT,
    serial_number      TEXT
);
CREATE TABLE IF NOT EXISTS zone ({_ENTITY},
    zone_kind   TEXT NOT NULL DEFAULT 'SEWERSHED',
    zone_basis  TEXT NOT NULL DEFAULT 'ADMINISTRATIVE',
    zone_code   TEXT
);
CREATE TABLE IF NOT EXISTS edge (
    id          INTEGER PRIMARY KEY,
    from_iri    TEXT NOT NULL,
    to_iri      TEXT NOT NULL,
    relation    TEXT NOT NULL,
    edge_basis  TEXT,
    props       TEXT NOT NULL DEFAULT '{{}}',
    valid_from  TEXT,
    valid_to    TEXT,
    UNIQUE (from_iri, to_iri, relation)
);
CREATE INDEX IF NOT EXISTS edge_from ON edge (from_iri);
CREATE INDEX IF NOT EXISTS edge_to ON edge (to_iri);

CREATE TABLE IF NOT EXISTS observed_property (
    iri            TEXT PRIMARY KEY,
    label          TEXT NOT NULL,
    property_kind  TEXT NOT NULL,
    default_unit   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS datastream (
    iri                  TEXT PRIMARY KEY,
    label                TEXT NOT NULL DEFAULT '',
    sensor               TEXT NOT NULL,
    observed_property    TEXT NOT NULL REFERENCES observed_property (iri),
    feature_of_interest  TEXT NOT NULL,
    stream_role          TEXT NOT NULL DEFAULT 'RAW',
    sampling_interval    TEXT,
    datasource_tag       TEXT
);
CREATE TABLE IF NOT EXISTS observation_array (
    datastream        TEXT NOT NULL REFERENCES datastream (iri) ON DELETE CASCADE,
    result_kind       TEXT NOT NULL DEFAULT 'MEASUREMENT',
    start_ns          INTEGER NOT NULL,
    step_ns           INTEGER,           -- NULL when irregular: see times
    count             INTEGER NOT NULL,
    times             BLOB,              -- packed int64 ns, irregular series only
    "values"          BLOB NOT NULL,     -- packed float64
    quality           BLOB,              -- packed uint8 QualityFlag codes (optional)
    unit              TEXT NOT NULL,
    was_generated_by  TEXT NOT NULL DEFAULT '',
    result_time       TEXT,
    PRIMARY KEY (datastream, result_kind)
);

CREATE TABLE IF NOT EXISTS attribute_definition (
    key            TEXT PRIMARY KEY,
    label          TEXT NOT NULL,
    value_type     TEXT NOT NULL,       -- float | int | str | bool | choice | datetime
    unit           TEXT NOT NULL DEFAULT '',
    category       TEXT NOT NULL DEFAULT 'Attributes',
    minimum        REAL,
    maximum        REAL,
    decimals       INTEGER,
    choices        TEXT NOT NULL DEFAULT '[]',
    description    TEXT NOT NULL DEFAULT '',
    applies_to     TEXT NOT NULL DEFAULT '[]',   -- class_iri list; empty = any
    ontology_slot  INTEGER NOT NULL DEFAULT 0    -- 1 when key is a wsys slot (exported)
);
CREATE TABLE IF NOT EXISTS attribute_measurement (
    id                   INTEGER PRIMARY KEY,
    feature_of_interest  TEXT NOT NULL,
    attribute            TEXT NOT NULL REFERENCES attribute_definition (key),
    measured_value       REAL,
    measured_text        TEXT,
    measured_unit        TEXT NOT NULL DEFAULT '',
    measurement_source   TEXT NOT NULL DEFAULT 'MANUAL',
    phenomenon_time      TEXT NOT NULL,
    UNIQUE (feature_of_interest, attribute)
);

CREATE TABLE IF NOT EXISTS incident (
    iri                  TEXT PRIMARY KEY,
    class_iri            TEXT NOT NULL,
    label                TEXT NOT NULL DEFAULT '',
    incident_type        TEXT NOT NULL DEFAULT 'STORM',
    started_at           TEXT NOT NULL,
    ended_at             TEXT NOT NULL,
    feature_of_interest  TEXT,
    part_of              TEXT,
    props                TEXT NOT NULL DEFAULT '{{}}'
);
CREATE TABLE IF NOT EXISTS event_group (name TEXT PRIMARY KEY, definition TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS site_dataset (
    name                TEXT PRIMARY KEY,
    site_iri            TEXT,
    rain_stream         TEXT,
    flow_stream         TEXT,
    temperature_stream  TEXT,
    spec                TEXT NOT NULL      -- DatasetSpec JSON (source, columns, periods)
);
CREATE TABLE IF NOT EXISTS model_spec (name TEXT PRIMARY KEY, spec TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS run (id TEXT PRIMARY KEY, position INTEGER NOT NULL, meta TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS run_array (run_id TEXT PRIMARY KEY REFERENCES run (id) ON DELETE CASCADE, data BLOB);
CREATE TABLE IF NOT EXISTS setting (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE VIEW IF NOT EXISTS node AS
    SELECT iri, class_iri, label, description, geometry, 'site' AS kind FROM monitoring_site
    UNION ALL SELECT iri, class_iri, label, description, geometry, 'sensor' FROM sensor
    UNION ALL SELECT iri, class_iri, label, description, geometry, 'zone' FROM zone;
"""

WSYS = "https://w3id.org/wsys/"

#: Observed properties seeded into every project (QUDT unit IRIs).
OBSERVED_PROPERTIES = (
    ("wsys:prop/flow", "Flow", "FLOW", "unit:FT3-PER-SEC"),
    ("wsys:prop/base_flow", "Base flow", "FLOW", "unit:FT3-PER-SEC"),
    ("wsys:prop/rainfall_depth", "Rainfall depth", "RAINFALL_DEPTH", "unit:IN"),
    ("wsys:prop/temperature", "Air temperature", "TEMPERATURE", "unit:DEG_C"),
    ("wsys:prop/depth", "Depth", "DEPTH", "unit:FT"),
    ("wsys:prop/velocity", "Velocity", "VELOCITY", "unit:FT-PER-SEC"),
)

#: Attribute definitions available in every project.  ``ontology_slot`` keys are wsys slots.
ATTRIBUTE_DEFINITIONS = (
    # key, label, type, unit, category, min, max, decimals, choices, description, applies_to, ontology
    ("shv:contributing_area", "Contributing area", "float", "acres", "Hydrology", 0.0, None, 2, (),
     "Area draining to the site (used to scale RDII models).", (), 0),
    ("shv:capacity_flow", "System capacity flow", "float", "cfs", "Hydrology", 0.0, None, 3, (),
     "Capacity flow Qc used by the MSDGC Qcritical criterion.", (), 0),
    ("shv:pipe_diameter", "Pipe diameter", "float", "in", "Asset", 0.0, None, 1, (),
     "Diameter of the monitored pipe.", (), 0),
    ("invert_elevation", "Invert elevation", "float", "ft", "Asset", None, None, 2, (),
     "Elevation of the invert (wsys Node.invert_elevation).", (), 1),
    ("rim_elevation", "Rim elevation", "float", "ft", "Asset", None, None, 2, (),
     "Elevation of the rim (wsys Node.rim_elevation).", (), 1),
    ("vertical_datum", "Vertical datum", "choice", "", "Asset", None, None, None,
     ("NAVD88", "NGVD29", "LOCAL"), "Datum of the elevations (wsys Asset.vertical_datum).", (), 1),
    ("shv:land_use", "Land use", "str", "", "Hydrology", None, None, None, (),
     "Dominant land use upstream of the site.", (), 0),
)

__all__ = ["APPLICATION_ID", "ATTRIBUTE_DEFINITIONS", "DDL", "OBSERVED_PROPERTIES", "SCHEMA_VERSION", "WSYS"]
