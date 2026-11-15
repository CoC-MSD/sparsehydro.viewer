"""Optional basemap: slippy-map tiles drawn under the map's features.

Off by default.  Requesting tiles tells the tile server which area is being
viewed, so the layer is only created when the user enables it; until then the
map makes no network requests.  Tiles are cached on disk.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QObject, QRectF, QTimer, QUrl
from PySide6.QtGui import QImage
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkDiskCache, QNetworkReply, QNetworkRequest

from ..core.geometry import tile_bounds, tile_range, tile_zoom

DEFAULT_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
DEFAULT_ATTRIBUTION = "© OpenStreetMap contributors"
MAX_TILES = 48  # per view; keeps requests modest and respects tile-server usage policies


class TileLayer(QObject):
    """Fetches and draws the tiles covering a :class:`~.map_view.MapView`'s visible area."""

    def __init__(self, view, cache_dir: Path, url: str = DEFAULT_URL, user_agent: str = "sparsehydro-viewer") -> None:
        super().__init__(view)
        self.view = view
        self.url = url
        self.user_agent = user_agent
        self.net = QNetworkAccessManager(self)
        cache = QNetworkDiskCache(self)
        cache.setCacheDirectory(str(cache_dir))
        cache.setMaximumCacheSize(200 * 1024 * 1024)
        self.net.setCache(cache)
        self.net.finished.connect(self._loaded)
        self._items: dict[tuple[int, int, int], pg.ImageItem] = {}
        self._pending: set[tuple[int, int, int]] = set()
        self._zoom = -1
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.update_tiles)
        view.getViewBox().sigRangeChanged.connect(lambda *_: self._timer.start())
        self.update_tiles()

    def remove(self) -> None:
        for item in self._items.values():
            self.view.removeItem(item)
        self._items.clear()
        self.net.finished.disconnect(self._loaded)
        self.deleteLater()

    def wanted(self) -> list[tuple[int, int, int]]:
        vb = self.view.getViewBox()
        (x0, x1), (y0, y1) = vb.viewRange()
        width_px = max(1.0, vb.width())
        z = tile_zoom((x1 - x0) / width_px)
        cols, rows = tile_range(x0, y0, x1, y1, z)
        tiles = [(z, x, y) for x in cols for y in rows]
        while len(tiles) > MAX_TILES and z > 0:  # very wide windows: drop a level
            z -= 1
            cols, rows = tile_range(x0, y0, x1, y1, z)
            tiles = [(z, x, y) for x in cols for y in rows]
        return tiles

    def update_tiles(self) -> None:
        tiles = self.wanted()
        z = tiles[0][0] if tiles else 0
        if z != self._zoom:  # new zoom level: old tiles go once the new ones arrive
            self._zoom = z
            for key in [k for k in self._items if k[0] != z]:
                self.view.removeItem(self._items.pop(key))
        for key in tiles:
            if key not in self._items and key not in self._pending:
                self._request(key)

    def _request(self, key: tuple[int, int, int]) -> None:
        z, x, y = key
        req = QNetworkRequest(QUrl(self.url.format(z=z, x=x, y=y)))
        req.setRawHeader(b"User-Agent", self.user_agent.encode())
        req.setAttribute(QNetworkRequest.Attribute.CacheLoadControlAttribute,
                         QNetworkRequest.CacheLoadControl.PreferCache)
        reply = self.net.get(req)
        reply.setProperty("tile", list(key))
        self._pending.add(key)

    def _loaded(self, reply: QNetworkReply) -> None:
        key = tuple(reply.property("tile") or ())
        self._pending.discard(key)  # type: ignore[arg-type]
        data = reply.readAll()
        ok = reply.error() == QNetworkReply.NetworkError.NoError
        reply.deleteLater()
        if not ok or len(key) != 3 or key[0] != self._zoom:
            return
        img = QImage.fromData(data)
        if img.isNull():
            return
        img = img.convertToFormat(QImage.Format.Format_RGBA8888)
        arr = np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.width(), 4).copy()
        item = pg.ImageItem(arr[::-1], axisOrder="row-major")  # image rows run top-down; the view's y runs up
        left, bottom, w, h = tile_bounds(key[1], key[2], key[0])
        item.setRect(QRectF(left, bottom, w, h))
        item.setZValue(-100)
        self.view.addItem(item, ignoreBounds=True)
        self._items[key] = item  # type: ignore[index]

    def tiles_shown(self) -> Iterable[tuple[int, int, int]]:
        return self._items.keys()


__all__ = ["DEFAULT_ATTRIBUTION", "DEFAULT_URL", "TileLayer"]
