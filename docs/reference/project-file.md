# Project file

A project is one SQLite database with the extension `.shproj` (`PRAGMA application_id` "SHPJ"). It can be opened
with any SQLite tool. The application edits a copy in memory and writes it back on **Save**.

## Tables and the water ontology

Tables that describe the monitored system use the class and slot names of the water ontology
(`water-ontology/schema`, LinkML, `wsys:` namespace), so their rows can be exported as ontology rows unchanged.
Every row has an `iri` (`wsys:<kind>/local/<slug>-<id>`), a `class_iri`, `label`, `description`, `alt_ids` (JSON),
`source_system` and, where it applies, `geometry` as WKT in EPSG:4326.

| Table | Ontology class | Holds |
| --- | --- | --- |
| `monitoring_site` | MonitoringSite | Flow meter sites, rain gauge sites, any monitored place (point location). |
| `sensor` | Sensor | `sensor_kind` (FLOW_METER, RAIN_GAGE, ...), attached to a site by an edge. |
| `zone` | Zone | Sewersheds and drainage areas (polygon or multipolygon), `zone_kind`. |
| `edge` | Edge | Relations: `ATTACHED_TO` (sensor to site), `BELONGS_TO_ZONE` (site to zone), `USES_GAGE`, ... |
| `observed_property` | ObservedProperty | Flow, rainfall depth, temperature, ... with units. |
| `datastream` | Datastream | One time series: sensor, observed property, feature of interest, role. |
| `observation_array` | Observation (packed) | The series values: regular time axes stored as start and step, values compressed losslessly. |
| `attribute_measurement` | AttributeMeasurement | Current attribute values of sites and zones, with unit and source. |
| `incident` | Incident | Storm events (`incident_type` STORM). |

## Viewer tables

| Table | Holds |
| --- | --- |
| `attribute_definition` | Attribute keys with label, type, unit, limits, choices and description. Ontology slots are pre-declared; custom keys start with `shv:` and are not exported to the ontology. |
| `site_dataset` | Datasets: which rain, flow and temperature datastreams, and the calibration and validation periods. |
| `model_spec` | Saved model structures (component trees with parameter overrides). |
| `run`, `run_array` | Calibration runs: configuration, status, Pareto set and per-report history. |
| `event_group` | Named event groups and filters. |
| `setting`, `meta` | Project settings (objectives, optimizer, interface state, schema markers). |

## Compatibility

- Projects saved as folders (`project.json` with `runs/*.npz`) by early versions are imported into a new `.shproj`
  when opened.
- Projects saved with step-based unit hydrograph parameters (before sparsehydro 1.0.0b1) are converted to hours once:
  models, the working model and every run's Pareto set; the project is then marked (`uh_schema` 2).
- A saved optimizer that is not installed is replaced by the closest installed one (NSGA-II from Platypus and from
  pymoo convert into each other at the same evaluation budget), with a note.
- Attribute definitions added by newer versions (for example *Average dry weather flow* and *Sewer system*) are
  added to older projects when opened.
