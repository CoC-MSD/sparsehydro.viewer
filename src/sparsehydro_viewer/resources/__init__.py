"""Bundled resources: theme-tinted SVG icons.

Icons are drawn with ``currentColor``; :func:`icon` substitutes a colour
(by default the theme's text colour) and renders them crisply at any size.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

ICON_DIR = Path(__file__).parent / "icons"
APP_ICON_SVG = Path(__file__).parent / "app-icon.svg"
APP_ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def app_icon() -> QIcon:
    """The application's own (full-colour) icon, used for windows, the taskbar and the installer."""
    renderer = QSvgRenderer(str(APP_ICON_SVG))
    ic = QIcon()
    for size in APP_ICON_SIZES:
        pm = QPixmap(QSize(size, size))
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()
        ic.addPixmap(pm)
    return ic


def _png_bytes(size: int) -> bytes:
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QImage

    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(str(APP_ICON_SVG)).render(painter, QRectF(0, 0, size, size))
    painter.end()
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buf, "PNG")
    return bytes(data.data())


def write_app_ico(out: Path, sizes=APP_ICON_SIZES) -> Path:
    """Write the application icon as a Windows ``.ico`` (PNG entries, one per size); needs a Qt application.

    Used for the executable and installer (``packaging/make_icon.py``) and, at run time, for the taskbar
    button's relaunch icon (see :mod:`sparsehydro_viewer.platform`).
    """
    import struct

    images = [(s, _png_bytes(s)) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for size, png in images:
        dim = 0 if size >= 256 else size  # 0 means 256 in the ICO directory
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset)
        blobs += png
        offset += len(png)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(header + entries + blobs)
    return out


def icon_names() -> list[str]:
    return sorted(p.stem for p in ICON_DIR.glob("*.svg"))


@lru_cache(maxsize=256)
def _svg(name: str) -> str:
    return (ICON_DIR / f"{name}.svg").read_text(encoding="utf-8")


def icon(name: str, color: str | None = None, disabled_color: str | None = None) -> QIcon:
    """A :class:`QIcon` for ``icons/<name>.svg`` drawn in *color* (theme text colour by default)."""
    from .. import theme

    t = theme.current()
    ic = QIcon()
    for mode, col in ((QIcon.Mode.Normal, color or t.text), (QIcon.Mode.Disabled, disabled_color or t.muted)):
        for size in (16, 20, 24, 32, 48):
            ic.addPixmap(_render(name, col, size), mode)
    return ic


@lru_cache(maxsize=1024)
def _render(name: str, color: str, size: int) -> QPixmap:
    svg = _svg(name).replace("currentColor", color)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pm = QPixmap(QSize(size, size))
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return pm


__all__ = ["APP_ICON_SIZES", "APP_ICON_SVG", "ICON_DIR", "app_icon", "icon", "icon_names", "write_app_ico"]
