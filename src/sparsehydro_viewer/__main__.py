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
    parser.add_argument("--self-test", metavar="REPORT",
                        help="check the installation (models, solvers in worker processes, project file, window), "
                             "write a report to REPORT and exit with 0 if every required check passed")
    args = parser.parse_args(argv)

    if args.self_test:
        from .selftest import run_self_test

        return run_self_test(args.self_test)
    if args.version:
        from . import __version__

        print(__version__)
        return 0

    from .app import run

    return run(project=args.project)


if __name__ == "__main__":
    sys.exit(main())
