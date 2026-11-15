# Third-party notices

sparsehydro-viewer is MIT-licensed. It depends on, and the Windows installer redistributes, the
following components under their own licences.

| Component | Licence | Notes |
| --- | --- | --- |
| Qt 6 and PySide6 (Qt for Python) | GNU LGPL v3 | Dynamically linked. The installer ships the unmodified PySide6/Qt libraries as separate files (one-folder build), so they can be replaced with a compatible build. Source: https://code.qt.io and https://download.qt.io/official_releases/QtForPython/ |
| pyqtgraph | MIT | https://github.com/pyqtgraph/pyqtgraph |
| sparsehydro | MIT | https://github.com/CoC-MSD/SparseHydro |
| NumPy, pandas, SciPy | BSD-3-Clause | |
| pymoo | Apache-2.0 | |
| Platypus (platypus-opt) | GPL-3.0 | Optional at runtime: only the Platypus-based optimizers use it. Bundling it in a distributed installer brings GPL-3.0 obligations for that build; see "Installer builds" below. |
| PyTorch | BSD-3-Clause | Currently a core dependency of sparsehydro; excluded from the installer because the viewer does not use it. |

## LGPL v3 (Qt / PySide6)

The full licence text is at https://www.gnu.org/licenses/lgpl-3.0.html and is included with the
PySide6 wheel (`PySide6/LICENSES`). You may replace the Qt and PySide6 libraries in the installed
application folder with your own builds of the same major version.

## Installer builds

`packaging/sparsehydro-viewer.spec` excludes `platypus` by default, so the Windows installer contains
only permissively licensed and LGPL components; the Platypus optimizers then report that the package
is missing. Builds that need them can remove the exclusion, and must then be distributed under
terms compatible with the GPL-3.0.
