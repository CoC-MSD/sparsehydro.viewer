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


__all__ = ["ICON_DIR", "icon", "icon_names"]
