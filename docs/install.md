# Installation

## Windows installer

Each [GitHub release](https://github.com/CoC-MSD/sparsehydro.viewer/releases) has a Windows installer
(`sparsehydro-viewer-<version>-setup.exe`). It installs for the current user by default (no administrator rights
needed), adds a Start menu entry, and can associate `.shproj` project files with the viewer. Python is not needed.

The installer includes GIS import (file geodatabases, shapefiles, ...). Its multi-objective optimizer is NSGA-II from
pymoo: the Platypus optimizers (NSGA-III, SPEA2, OMOPSO, ...) are GPL-licensed and left out of the installer; see
[Licences](#licences).

## With pip

```bash
pip install "sparsehydro-viewer[gis]"
sparsehydro-viewer                 # or: python -m sparsehydro_viewer [project.shproj]
```

The viewer needs sparsehydro 1.0.0b1 or later; until it is on PyPI, install it first:

```bash
pip install "sparsehydro @ git+https://github.com/CoC-MSD/SparseHydro@v1.0.0b1"
```

Optional extras:

| Extra | Adds |
| --- | --- |
| `gis` | Import and export of sewersheds and sites (pyogrio, pyproj) |
| `pymoo` | NSGA-II from pymoo, as in the Windows installer |
| `dev` | Tests and linting (includes both of the above) |
| `docs` | This documentation |

## With conda

A conda environment avoids mixing pip and conda Qt libraries on Windows:

```bash
conda create -n sparsehydro-viewer -c conda-forge python=3.13 pyside6 pyqtgraph numpy pandas scipy pyogrio pyproj
conda activate sparsehydro-viewer
pip install "sparsehydro @ git+https://github.com/CoC-MSD/SparseHydro@v1.0.0b1"
pip install --no-deps sparsehydro-viewer
```

## Checking an installation

```bash
sparsehydro-viewer --self-test report.txt
```

writes a report and exits with 0 when everything required works: every unit hydrograph, composed models and their
traces, a small calibration in a separate worker process with each installed optimizer, a project file round trip,
GIS import (when installed) and the main window. Optional parts that are not installed are reported as
"unavailable". The release workflow runs the same check on the Windows build before making the installer.

(licences)=
## Licences

The viewer is MIT-licensed. It uses Qt through PySide6 under the LGPL v3; the installer ships the Qt libraries as
separate, replaceable files. Platypus (GPL-3.0) is used when installed with pip and is not bundled in the installer.
`THIRD_PARTY_NOTICES.md` lists every component and its licence.
