"""Entry point: ``sparsehydro-viewer`` or ``python -m sparsehydro_viewer``."""

from __future__ import annotations

import argparse
import multiprocessing
import sys


def main(argv: list[str] | None = None) -> int:
    """Launch the desktop application.

    :param argv: Command-line arguments (defaults to ``sys.argv[1:]``).
    :returns: Process exit code.
    """
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser(prog="sparsehydro-viewer")
    parser.add_argument("project", nargs="?", help="project folder to open")
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    args = parser.parse_args(argv)

    if args.version:
        from . import __version__

        print(__version__)
        return 0

    from .app import run

    return run(project=args.project)


if __name__ == "__main__":
    sys.exit(main())
