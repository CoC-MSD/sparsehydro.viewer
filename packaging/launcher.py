"""Frozen-build entry point (PyInstaller needs a script, not a module path)."""

import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()  # calibration workers are spawned processes
    from sparsehydro_viewer.__main__ import main

    sys.exit(main())
