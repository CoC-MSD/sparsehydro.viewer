"""Windows taskbar identity: icon file, relaunch command, window properties."""

from __future__ import annotations

import struct
import sys

import pytest

from sparsehydro_viewer import platform as plat


def test_ico_file_is_written_once_and_valid(qtbot, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("platformdirs.user_cache_dir", lambda *_a, **_k: str(tmp_path))
    path = plat.icon_file()
    assert path is not None and path.parent == tmp_path and path.name.startswith("app-")
    reserved, kind, count = struct.unpack("<HHH", path.read_bytes()[:6])
    assert (reserved, kind, count) == (0, 1, 9)
    mtime = path.stat().st_mtime_ns
    assert plat.icon_file() == path and path.stat().st_mtime_ns == mtime  # reused, not rewritten


def test_relaunch_command_starts_the_viewer() -> None:
    cmd = plat.relaunch_command()
    assert cmd.startswith('"') and cmd.endswith("-m sparsehydro_viewer")


def test_apply_never_raises(qtbot) -> None:
    from PySide6.QtWidgets import QWidget

    w = QWidget()
    qtbot.addWidget(w)
    w.show()
    ok = plat.apply_taskbar_identity(w)  # offscreen windows have no real HWND: reported, not raised
    assert isinstance(ok, bool)
    if sys.platform != "win32":
        assert ok is False


@pytest.mark.skipif(sys.platform != "win32", reason="Windows taskbar only")
def test_window_properties_round_trip_on_a_real_window(qtbot) -> None:
    from PySide6.QtGui import QGuiApplication

    if QGuiApplication.platformName() != "windows":
        pytest.skip("needs the native Windows platform plugin (tests run offscreen)")
    from PySide6.QtWidgets import QWidget

    w = QWidget()
    qtbot.addWidget(w)
    w.show()
    assert plat.apply_taskbar_identity(w)
    hwnd = int(w.winId())
    assert plat.get_window_property(hwnd, plat.PID_ID) == plat.APP_USER_MODEL_ID
    assert plat.get_window_property(hwnd, plat.PID_RELAUNCH_ICON).endswith(".ico,0")
