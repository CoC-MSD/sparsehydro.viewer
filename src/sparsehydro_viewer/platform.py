"""Windows taskbar identity for the main window.

The process sets an explicit AppUserModelID (``sparsehydro.viewer``) so its
windows are grouped under the application rather than ``python.exe``. Windows
then looks for the taskbar button's icon and relaunch command among that ID's
properties, which a Start-menu shortcut normally supplies; when the viewer is
started from Python (no shortcut) the button can be blank. Setting the
window's own relaunch properties (System.AppUserModel.RelaunchIconResource,
RelaunchCommand, RelaunchDisplayNameResource, then ID) through its property
store fixes that, as Microsoft documents for applications without shortcuts.

Everything here is a no-op off Windows and never raises (a failure is logged).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)

APP_USER_MODEL_ID = "sparsehydro.viewer"
DISPLAY_NAME = "SparseHydro Viewer"

# System.AppUserModel.* property keys: fmtid {9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}, pid below.
_FMTID = "{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}"
PID_RELAUNCH_COMMAND, PID_RELAUNCH_ICON, PID_RELAUNCH_NAME, PID_ID = 2, 3, 4, 5
_IID_PROPERTY_STORE = "{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}"
_VT_LPWSTR = 31


def relaunch_command() -> str:
    """How Windows should start the viewer again from its taskbar button."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")  # no console window when relaunched
    return f'"{pythonw if pythonw.exists() else exe}" -m sparsehydro_viewer'


def icon_file() -> Path | None:
    """The application ``.ico`` (beside a frozen executable, else written once to the user cache)."""
    if getattr(sys, "frozen", False):
        bundled = Path(sys.executable).with_name("app.ico")
        if bundled.exists():
            return bundled
    try:
        import hashlib

        from platformdirs import user_cache_dir

        from .resources import APP_ICON_SVG, write_app_ico

        digest = hashlib.sha1(APP_ICON_SVG.read_bytes()).hexdigest()[:10]  # a new file only when the icon changes
        path = Path(user_cache_dir("sparsehydro-viewer")) / f"app-{digest}.ico"
        if not path.exists():
            write_app_ico(path)
        return path
    except Exception as exc:  # noqa: BLE001
        log.debug("no taskbar icon file: %s", exc)
        return None


def _com():
    """ctypes declarations for IPropertyStore (Windows only)."""
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_ubyte * 8)]

    class PROPERTYKEY(ctypes.Structure):
        _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]

    class PROPVARIANT(ctypes.Structure):
        _fields_ = [("vt", wintypes.USHORT), ("r1", wintypes.USHORT), ("r2", wintypes.USHORT),
                    ("r3", wintypes.USHORT), ("value", ctypes.c_void_p), ("pad", ctypes.c_void_p)]

    def guid(text: str) -> GUID:
        g = GUID()
        ctypes.windll.ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(g))
        return g

    proto = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(PROPERTYKEY),
                               ctypes.POINTER(PROPVARIANT))
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)
    commit = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p)
    return ctypes, GUID, PROPERTYKEY, PROPVARIANT, guid, proto, release, commit


def _store(hwnd: int):
    ctypes, _GUID, _PK, _PV, guid, *_ = _com()
    store = ctypes.c_void_p()
    iid = guid(_IID_PROPERTY_STORE)
    hr = ctypes.windll.shell32.SHGetPropertyStoreForWindow(ctypes.c_void_p(hwnd), ctypes.byref(iid),
                                                          ctypes.byref(store))
    if hr != 0 or not store:
        raise OSError(f"SHGetPropertyStoreForWindow failed (0x{hr & 0xFFFFFFFF:08X})")
    return store


def _method(store, index: int, prototype):
    import ctypes

    vtable = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return prototype(vtable[index])


def set_window_properties(hwnd: int, values: dict[int, str]) -> None:
    """Set System.AppUserModel string properties (by pid) on a window, in the given order."""
    ctypes, _GUID, PROPERTYKEY, PROPVARIANT, guid, proto, release, commit = _com()
    store = _store(hwnd)
    try:
        set_value = _method(store, 6, proto)  # IPropertyStore::SetValue
        for pid, text in values.items():
            key = PROPERTYKEY(guid(_FMTID), pid)
            buf = ctypes.create_unicode_buffer(text)
            pv = PROPVARIANT(vt=_VT_LPWSTR, value=ctypes.cast(buf, ctypes.c_void_p).value)
            hr = set_value(store, ctypes.byref(key), ctypes.byref(pv))
            if hr != 0:
                raise OSError(f"IPropertyStore::SetValue({pid}) failed (0x{hr & 0xFFFFFFFF:08X})")
        _method(store, 7, commit)(store)  # IPropertyStore::Commit
    finally:
        _method(store, 2, release)(store)  # IUnknown::Release


def get_window_property(hwnd: int, pid: int) -> str | None:
    """Read a System.AppUserModel string property of a window (``None`` when unset)."""
    ctypes, _GUID, PROPERTYKEY, PROPVARIANT, guid, proto, release, _commit = _com()
    store = _store(hwnd)
    try:
        key = PROPERTYKEY(guid(_FMTID), pid)
        pv = PROPVARIANT()
        hr = _method(store, 5, proto)(store, ctypes.byref(key), ctypes.byref(pv))  # IPropertyStore::GetValue
        if hr != 0 or pv.vt != _VT_LPWSTR or not pv.value:
            return None
        text = ctypes.wstring_at(pv.value)
        ctypes.windll.ole32.PropVariantClear(ctypes.byref(pv))
        return text
    finally:
        _method(store, 2, release)(store)


def apply_taskbar_identity(window) -> bool:
    """Give *window*'s taskbar button the application's icon, name and relaunch command.

    :returns: ``True`` when the properties were set (Windows only).
    """
    if sys.platform != "win32":
        return False
    try:
        icon = icon_file()
        values = {}
        if icon is not None:
            values[PID_RELAUNCH_ICON] = f"{icon},0"
        values[PID_RELAUNCH_COMMAND] = relaunch_command()
        values[PID_RELAUNCH_NAME] = DISPLAY_NAME
        values[PID_ID] = APP_USER_MODEL_ID  # the ID last, after its relaunch properties
        set_window_properties(int(window.winId()), values)
        return True
    except Exception as exc:  # noqa: BLE001 - cosmetic: never stop the application for this
        log.warning("could not set the taskbar identity: %s", exc)
        return False


__all__ = ["APP_USER_MODEL_ID", "apply_taskbar_identity", "get_window_property", "icon_file", "relaunch_command",
           "set_window_properties"]
