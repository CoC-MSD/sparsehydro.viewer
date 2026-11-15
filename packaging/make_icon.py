"""Build ``packaging/app.ico`` (Windows executable, installer and ``.shproj`` icon) from the SVG.

Run before PyInstaller:  python packaging/make_icon.py

Each size is rendered by Qt from ``src/sparsehydro_viewer/resources/app-icon.svg`` and stored as a
PNG entry in the ICO container (supported by Windows Vista and later), so no imaging library is needed.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def png_bytes(svg: Path, size: int) -> bytes:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(str(svg)).render(painter, QRectF(0, 0, size, size))
    painter.end()
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buf, "PNG")
    return bytes(data.data())


def write_ico(svg: Path, out: Path, sizes=ICO_SIZES) -> Path:
    from PySide6.QtGui import QGuiApplication

    _app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])  # noqa: F841 (Qt needs an application)
    images = [(s, png_bytes(svg, s)) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for size, png in images:
        dim = 0 if size >= 256 else size  # 0 means 256 in the ICO directory
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset)
        blobs += png
        offset += len(png)
    out.write_bytes(header + entries + blobs)
    return out


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    target = write_ico(root.parent / "src" / "sparsehydro_viewer" / "resources" / "app-icon.svg", root / "app.ico")
    print(f"wrote {target}")
