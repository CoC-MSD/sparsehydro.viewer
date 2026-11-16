"""Build ``packaging/app.ico`` (Windows executable, installer and ``.shproj`` icon) from the SVG.

Run before PyInstaller:  python packaging/make_icon.py

Each size is rendered by Qt from ``src/sparsehydro_viewer/resources/app-icon.svg`` and stored as a PNG entry
in the ICO container (supported by Windows Vista and later); see
:func:`sparsehydro_viewer.resources.write_app_ico`.
"""

from __future__ import annotations

import sys
from pathlib import Path

ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def write_ico(_svg: Path, out: Path, sizes=ICO_SIZES) -> Path:
    from PySide6.QtGui import QGuiApplication

    from sparsehydro_viewer.resources import write_app_ico

    _app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])  # noqa: F841 (Qt needs an application)
    return write_app_ico(out, sizes)


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    target = write_ico(root.parent / "src" / "sparsehydro_viewer" / "resources" / "app-icon.svg", root / "app.ico")
    print(f"wrote {target}")
