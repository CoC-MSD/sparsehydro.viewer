API (core)
==========

``sparsehydro_viewer.core`` is the Qt-free part of the application: specifications, catalogs, evaluation, events,
assessment, GIS and persistence. It is the only layer, with ``services``, that imports sparsehydro, and can be used
from scripts and notebooks.

Models and catalogs
-------------------

.. automodule:: sparsehydro_viewer.core.catalog
   :members: ModelSpec, ParameterState, ModelCatalog, build_uh

.. automodule:: sparsehydro_viewer.core.solvers
   :members: SolverSpec, SolverEntry, SolverCatalog

.. automodule:: sparsehydro_viewer.core.objectives
   :members: ObjectiveSpec

Data and evaluation
-------------------

.. automodule:: sparsehydro_viewer.core.data
   :members: DatasetSpec, Period, load_dataset

.. automodule:: sparsehydro_viewer.core.evaluation
   :members: Evaluator

.. automodule:: sparsehydro_viewer.core.trace
   :members:

Calibration runs
----------------

.. automodule:: sparsehydro_viewer.core.calibration
   :members: CalibrationPayload, run_calibration

.. automodule:: sparsehydro_viewer.core.runs
   :members: RunRecord

.. automodule:: sparsehydro_viewer.core.diagnostics
   :members: fit_statistics, information_criteria, complexity_front, hypervolume, front_history, FrontHistory

Events and assessment
---------------------

.. automodule:: sparsehydro_viewer.core.events
   :members: EventConfig, ConfigFit, EventAnalysis, EventOverrides, run_event_analysis

.. automodule:: sparsehydro_viewer.core.assess
   :members: run_assessment, detect_events

Project, geometry and GIS
-------------------------

.. automodule:: sparsehydro_viewer.core.project
   :members: Project

.. automodule:: sparsehydro_viewer.core.geometry
   :members: parse_point, parse_polygons, polygons_wkt, point_in_polygons, spherical_area_m2, to_mercator, from_mercator

.. automodule:: sparsehydro_viewer.core.gis
   :members: read_layer, list_layers, ImportPlan, ColumnPlan, import_layer, link_sites_to_zones, export_nodes, area_acres
