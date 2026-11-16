"""Light/dark theme: Qt palette, a small stylesheet and plot colours."""

from __future__ import annotations

from dataclasses import dataclass

import pyqtgraph as pg
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

#: Colour-blind-safe categorical palette (Okabe-Ito order, blue first).
CATEGORICAL = ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9", "#D55E00", "#F0E442", "#7F7F7F"]


@dataclass(frozen=True)
class Theme:
    name: str
    window: str
    base: str
    alt_base: str
    text: str
    muted: str
    border: str
    accent: str
    plot_bg: str
    plot_fg: str
    observed: str
    rain: str
    predicted: str
    selection: str
    band: str
    event_fill: str
    #: Text drawn on the accent colour (selected navigation item, primary buttons, highlighted rows).
    on_accent: str = "#ffffff"


LIGHT = Theme("light", "#f5f6f8", "#ffffff", "#f0f2f5", "#1d232b", "#5d6773", "#d5dae1", "#0b6bcb",
              "#ffffff", "#3a424d", "#1d232b", "#4f8fd6", "#E66100", "#D81B60", "#E6610040", "#0b6bcb18")
# White on the dark theme's light blue accent is only 2.7:1, so text on it is dark (about 7:1).
DARK = Theme("dark", "#1b1f24", "#22272e", "#2a3038", "#e3e8ee", "#9aa5b1", "#3a424d", "#4ea1ff",
             "#1e2228", "#c5ccd4", "#e3e8ee", "#5b9bd5", "#FF9F45", "#FF4F8B", "#FF9F4540", "#4ea1ff22",
             on_accent="#0d1117")
#: Black background, white text and lines, yellow accent: for low vision and bright surroundings.
HIGH_CONTRAST = Theme("high-contrast", "#000000", "#000000", "#141414", "#ffffff", "#e6e6e6", "#ffffff",
                      "#ffd400", "#000000", "#ffffff", "#ffffff", "#4fc3ff", "#ff9e3d", "#00e5ff", "#ffd40050",
                      "#ffd40038", on_accent="#000000")

#: Themes by the name stored in the settings.
THEMES = {t.name: t for t in (LIGHT, DARK, HIGH_CONTRAST)}
THEME_LABELS = {"light": "&Light theme", "dark": "&Dark theme", "high-contrast": "&High-contrast theme"}

_current: Theme = LIGHT


def current() -> Theme:
    return _current


def by_name(name: str | None) -> Theme:
    """The theme saved as *name* (light when unknown)."""
    return THEMES.get(name or "", LIGHT)


def _luminance(color: str) -> float:
    h = color.lstrip("#")[:6]
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast_ratio(a: str, b: str) -> float:
    """WCAG 2 contrast ratio of two ``#rrggbb`` colours (1 to 21; AA needs 4.5 for text, 3 for graphics)."""
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def series_color(i: int) -> str:
    return CATEGORICAL[i % len(CATEGORICAL)]


def plain_axes(plot) -> None:
    """Turn off pyqtgraph's automatic SI scaling (which would label an NSE of 0.8 as "800 (x0.001)")."""
    item = plot.getPlotItem() if hasattr(plot, "getPlotItem") else plot
    for name in ("left", "bottom", "right"):
        ax = item.getAxis(name)
        if ax is not None:
            ax.enableAutoSIPrefix(False)


def apply(app: QApplication, theme: Theme) -> None:
    """Apply *theme* to the application and to pyqtgraph defaults."""
    global _current
    _current = theme
    app.setStyle("Fusion")
    pal = QPalette()
    roles = {
        QPalette.ColorRole.Window: theme.window, QPalette.ColorRole.WindowText: theme.text,
        QPalette.ColorRole.Base: theme.base, QPalette.ColorRole.AlternateBase: theme.alt_base,
        QPalette.ColorRole.Text: theme.text, QPalette.ColorRole.Button: theme.alt_base,
        QPalette.ColorRole.ButtonText: theme.text, QPalette.ColorRole.Highlight: theme.accent,
        QPalette.ColorRole.HighlightedText: theme.on_accent, QPalette.ColorRole.ToolTipBase: theme.base,
        QPalette.ColorRole.ToolTipText: theme.text, QPalette.ColorRole.PlaceholderText: theme.muted,
        QPalette.ColorRole.Link: theme.accent, QPalette.ColorRole.Mid: theme.border,
    }
    for role, color in roles.items():
        pal.setColor(role, QColor(color))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(theme.muted))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(theme.muted))
    app.setPalette(pal)
    app.setStyleSheet(stylesheet(theme))
    pg.setConfigOptions(background=theme.plot_bg, foreground=theme.plot_fg, antialias=True)


def stylesheet(t: Theme) -> str:
    return f"""
    QMainWindow::separator {{ background: {t.border}; width: 1px; height: 1px; }}
    QListWidget#navRail {{ background: {t.alt_base}; border: none; border-right: 1px solid {t.border};
                           outline: 0; padding-top: 6px; }}
    QListWidget#navRail::item {{ padding-left: 8px; margin: 2px 6px; border-radius: 6px; color: {t.muted}; }}
    QListWidget#navRail::item:selected {{ background: {t.accent}; color: {t.on_accent}; }}
    QListWidget#navRail::item:hover:!selected {{ background: {t.border}; color: {t.text}; }}
    QLabel#pageTitle {{ font-size: 15pt; font-weight: 600; }}
    QLabel#hint {{ color: {t.muted}; }}
    QLabel#banner {{ background: {t.event_fill}; border: 1px solid {t.accent}; border-radius: 6px; padding: 6px 10px; }}
    QGroupBox {{ border: 1px solid {t.border}; border-radius: 6px; margin-top: 14px; padding-top: 6px; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; color: {t.muted}; font-weight: 600; }}
    QPushButton#primary {{ background: {t.accent}; color: {t.on_accent}; border: none; border-radius: 5px;
                           padding: 6px 14px; font-weight: 600; }}
    QPushButton#primary:focus {{ border: 2px solid {t.text}; }}
    QPushButton#primary:disabled {{ background: {t.border}; color: {t.muted}; }}
    QTableView, QTreeView {{ gridline-color: {t.border}; }}
    QDockWidget::title {{ padding: 4px 8px; background: {t.alt_base}; }}
    """
