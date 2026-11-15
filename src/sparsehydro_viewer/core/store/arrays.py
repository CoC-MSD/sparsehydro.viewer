"""Compact, exact encoding of numpy arrays and time axes for SQLite blobs."""

from __future__ import annotations

import io
import zlib

import numpy as np


def pack(values: np.ndarray) -> bytes:
    """Lossless, compressed bytes for a numeric array (dtype and shape preserved)."""
    buf = io.BytesIO()
    np.save(buf, np.ascontiguousarray(values), allow_pickle=False)
    return zlib.compress(buf.getvalue(), level=6)


def unpack(blob: bytes) -> np.ndarray:
    return np.load(io.BytesIO(zlib.decompress(blob)), allow_pickle=False)


def pack_time(times: np.ndarray) -> tuple[int, int | None, int, bytes | None]:
    """``(start_ns, step_ns or None, count, packed times or None)`` for a datetime64 axis.

    Regular axes (one step throughout) are stored as start + step only.
    """
    ns = np.asarray(times, dtype="datetime64[ns]").astype("int64")
    if ns.size == 0:
        return 0, None, 0, pack(ns)
    if ns.size == 1:
        return int(ns[0]), None, 1, None
    d = np.diff(ns)
    if (d == d[0]).all() and d[0] > 0:
        return int(ns[0]), int(d[0]), int(ns.size), None
    return int(ns[0]), None, int(ns.size), pack(ns)


def unpack_time(start_ns: int, step_ns: int | None, count: int, times: bytes | None) -> np.ndarray:
    if times is not None:
        return unpack(times).astype("datetime64[ns]")
    if step_ns is None:
        return np.array([start_ns], dtype="int64").astype("datetime64[ns]")[:count]
    return (start_ns + step_ns * np.arange(count, dtype="int64")).astype("datetime64[ns]")


__all__ = ["pack", "pack_time", "unpack", "unpack_time"]
