# PyInstaller spec: one-folder build (keeps Qt/PySide6 as replaceable shared libraries, as the LGPL expects).
# Build:  pyinstaller packaging/sparsehydro-viewer.spec --noconfirm
# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hidden = collect_submodules("sparsehydro_viewer") + collect_submodules("sparsehydro") + [
    "pymoo.algorithms.moo.nsga2",
    "pymoo.operators.crossover.sbx",
    "pymoo.operators.mutation.pm",
    "scipy.special._cdflib",
]

# torch is a declared dependency of sparsehydro but unused by the viewer; platypus is GPL-3.0 (see
# THIRD_PARTY_NOTICES.md); the remaining Qt modules are not used by the application.
excludes = [
    "torch", "platypus", "tkinter", "matplotlib", "IPython", "notebook", "streamlit",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore", "PySide6.QtMultimedia",
    "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtPdf",
]

a = Analysis(
    ["launcher.py"],
    pathex=[],
    hiddenimports=hidden,
    excludes=excludes,
    datas=[("../THIRD_PARTY_NOTICES.md", "."), ("../LICENSE", ".")],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="sparsehydro-viewer",
    console=False,
    icon="app.ico",  # built by packaging/make_icon.py
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="sparsehydro-viewer")
