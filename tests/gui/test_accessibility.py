"""Accessibility and finish: names, tooltips, keyboard reach and colour contrast (WCAG 2 AA)."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from sparsehydro_viewer import theme
from sparsehydro_viewer.views.accessibility import interactive_controls, needs_tooltip


@pytest.fixture
def window(qtbot):
    from sparsehydro_viewer.app import create_app
    from sparsehydro_viewer.views.main_window import MainWindow

    create_app()
    win = MainWindow()
    win.show()
    yield win
    win.ctx.session.set_dirty(False)
    win.ctx.calibration.shutdown()
    win.close()
    theme.apply(QApplication.instance(), theme.LIGHT)


def _describe(w) -> str:
    return f"{type(w).__name__} name={w.accessibleName()!r} parent={type(w.parentWidget()).__name__}"


def test_every_control_has_a_name_and_where_needed_a_tooltip(window, qtbot) -> None:
    for i in range(len(window.pages)):
        window.nav.setCurrentRow(i)
        qtbot.wait(10)
    controls = interactive_controls(window)
    assert len(controls) > 100
    unnamed = [_describe(w) for w in controls if not w.accessibleName().strip()]
    no_tip = [_describe(w) for w in controls if needs_tooltip(w) and not w.toolTip().strip()]
    assert not unnamed, unnamed
    assert not no_tip, no_tip


def test_toolbar_actions_explain_themselves(window) -> None:
    seen = 0
    for i, page in enumerate(window.pages):
        window.nav.setCurrentRow(i)
        for act in window.toolbar.actions():
            if act.isSeparator() or not act.isVisible() or act.text() == "":
                continue
            seen += 1
            tip = act.toolTip().strip()
            assert tip and tip != act.text().replace("&", ""), f"{page.title}: {act.text()!r} has no real tooltip"
    assert seen > 30
    for act in (window.new_action, window.open_action, window.save_action):
        assert "[" in act.toolTip() and act.statusTip()  # shortcut shown, and a status-bar tip


def test_pages_are_reachable_from_the_keyboard(window, qtbot) -> None:
    shortcuts = {a.shortcut().toString() for a in window.actions()}
    assert {f"Ctrl+{i + 1}" for i in range(len(window.pages))} <= shortcuts
    for i in range(len(window.pages)):
        window.nav.setCurrentRow(i)
        page = window.pages[i]
        reachable = [w for w in interactive_controls(page) if w.isVisible() and w.isEnabled()]
        not_tabbable = [_describe(w) for w in reachable
                        if not (w.focusPolicy() & Qt.FocusPolicy.TabFocus)
                        and type(w).__name__ not in ("QToolButton",)]  # toolbar-style buttons: reached via actions
        assert not not_tabbable, f"{page.title}: {not_tabbable}"


@pytest.mark.parametrize("t", list(theme.THEMES.values()), ids=list(theme.THEMES))
def test_theme_contrast_meets_wcag_aa(t) -> None:
    text = {"text on window": (t.text, t.window), "text on fields": (t.text, t.base),
            "secondary text": (t.muted, t.window), "secondary text on panels": (t.muted, t.alt_base),
            "text on accent": (t.on_accent, t.accent), "plot labels": (t.plot_fg, t.plot_bg)}
    graphics = {"observed": (t.observed, t.plot_bg), "simulated": (t.predicted, t.plot_bg),
                "accent lines": (t.accent, t.plot_bg)}
    low = {k: round(theme.contrast_ratio(*v), 2) for k, v in text.items() if theme.contrast_ratio(*v) < 4.5}
    low |= {k: round(theme.contrast_ratio(*v), 2) for k, v in graphics.items() if theme.contrast_ratio(*v) < 3.0}
    assert not low, f"{t.name}: {low}"


def test_high_contrast_theme_is_offered_and_remembered(window, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    window.settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)  # not the user's
    labels = [a.text() for a in window.menuBar().actions()[1].menu().actions()]
    assert "&High-contrast theme" in labels
    window.set_theme("high-contrast")
    assert theme.current() is theme.HIGH_CONTRAST
    assert window.settings.value("theme") == "high-contrast"
    window.set_theme("light")
