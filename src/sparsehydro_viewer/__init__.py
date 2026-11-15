"""sparsehydro-viewer: desktop workbench for sparsehydro models.

The package is layered so that only :mod:`sparsehydro_viewer.core` and
:mod:`sparsehydro_viewer.services` talk to :mod:`sparsehydro`; widgets and
views work with plain arrays, dataclasses and Qt models.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("sparsehydro-viewer")
except PackageNotFoundError:  # running from a source tree without installation
    __version__ = "0.0.0+unknown"

APP_NAME = "SparseHydro Viewer"
ORG_NAME = "sparsehydro"

__all__ = ["APP_NAME", "ORG_NAME", "__version__"]
