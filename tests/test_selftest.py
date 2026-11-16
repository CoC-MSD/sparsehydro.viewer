"""The installation self-test (also run on the frozen build by the release workflow)."""

from __future__ import annotations

import pytest

from sparsehydro_viewer.__main__ import main


@pytest.mark.slow
def test_self_test_passes_and_writes_a_report(tmp_path, qapp) -> None:
    report = tmp_path / "report.txt"
    code = main(["--self-test", str(report)])
    text = report.read_text(encoding="utf-8")
    assert code == 0, text
    assert text.startswith("sparsehydro-viewer self-test: PASSED")
    for check in ("unit hydrographs", "multi-objective optimizer installed", "calibration worker, NSGA-II (pymoo)",
                  "project file", "main window"):
        assert f"] {check} (" in text


def test_a_failing_check_fails_the_self_test(tmp_path, monkeypatch) -> None:
    from sparsehydro_viewer import selftest

    r = selftest._Report()
    r.check("broken", lambda: 1 / 0)
    r.check("optional", lambda: __import__("platypus_not_installed"), optional=True)
    assert r.failed == 1
    assert r.lines[0].startswith("[       FAIL] broken") and "ZeroDivisionError" in r.lines[0]
    assert r.lines[1].startswith("[unavailable] optional")
