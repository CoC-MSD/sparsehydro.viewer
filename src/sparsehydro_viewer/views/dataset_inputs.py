"""Which rain gauge and temperature series the analysis dataset uses - shown and changeable.

A dataset reads three series: the flow it is about, a rain series and,
optionally, a temperature series. Rain and temperature may come from any
site of the project (a rain gauge near the flow meter, an airport's
temperature). :class:`DatasetInputsBar` shows the current choice and lets
the user pick another series; the session then rebuilds the dataset and
every page that uses it follows.
"""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QMessageBox, QWidget

from ..core.project import PROP_RAIN, PROP_TEMPERATURE
from .context import AppContext


def series_text(entry: dict) -> str:
    """``label @ site  (2022-05-01 to 2022-05-21, 5 min)``."""
    step = entry["step_minutes"]
    every = "irregular" if step is None else f"{step:g} min"
    site = f" @ {entry['site_label']}" if entry["site_label"] else ""
    return f"{entry['label']}{site}  ({entry['start']:%Y-%m-%d} to {entry['end']:%Y-%m-%d}, {every})"


class DatasetInputsBar(QWidget):
    """Rain gauge and temperature pickers for the session's current dataset."""

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.rain = QComboBox()
        self.rain.setAccessibleName("Rain gauge series")
        self.rain.setToolTip("Rain series this dataset uses for simulation and calibration. Any rain series of the "
                             "project can be chosen, including a gauge at another site; it must overlap the flow "
                             "record in time.")
        self.temperature = QComboBox()
        self.temperature.setAccessibleName("Temperature series")
        self.temperature.setToolTip("Temperature series this dataset uses (needed by snowmelt and temperature-"
                                    "dependent losses), from any site, or none.")
        self.note = QLabel()
        self.note.setObjectName("hint")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        for text, combo in (("Rain gauge", self.rain), ("Temperature", self.temperature)):
            label = QLabel(text)
            label.setBuddy(combo)
            lay.addWidget(label)
            lay.addWidget(combo, 1)
        lay.addWidget(self.note)
        self._filling = False
        self.rain.currentIndexChanged.connect(lambda *_: self._changed("rain"))
        self.temperature.currentIndexChanged.connect(lambda *_: self._changed("temperature"))
        s = ctx.session
        for sig in (s.datasetChanged, s.projectChanged, s.nodesStructureChanged):
            sig.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        s = self.ctx.session
        ds = s.dataset
        self._filling = True
        try:
            for combo in (self.rain, self.temperature):
                combo.clear()
            usable = ds is not None and ds.stored
            self.setEnabled(bool(usable))
            if not usable:
                self.note.setText("" if ds is None else "(not stored in the project)")
                return
            store = s.store
            for e in store.series_catalog(PROP_RAIN):
                self.rain.addItem(series_text(e), e["iri"])
            self.temperature.addItem("(none)", None)
            for e in store.series_catalog(PROP_TEMPERATURE):
                self.temperature.addItem(series_text(e), e["iri"])
            self.rain.setCurrentIndex(max(self.rain.findData(ds.rain_stream), 0))
            self.temperature.setCurrentIndex(max(self.temperature.findData(ds.temperature_stream), 0))
            inputs = s.project.dataset_inputs(ds.name)
            away = [k for k in ("rain", "temperature")
                    if inputs[k] is not None and inputs[k]["site_iri"] != ds.site_iri]
            self.note.setText(f"({' and '.join(away)} from another site)" if away else "")
        finally:
            self._filling = False

    def _changed(self, which: str) -> None:
        if self._filling:
            return
        s = self.ctx.session
        ds = s.dataset
        if ds is None:
            return
        try:
            if which == "rain":
                if self.rain.currentData() != ds.rain_stream:
                    s.set_dataset_inputs(ds.name, rain_stream=self.rain.currentData())
            elif self.temperature.currentData() != ds.temperature_stream:
                s.set_dataset_inputs(ds.name, temperature_stream=self.temperature.currentData())
        except Exception as exc:  # noqa: BLE001 - e.g. no overlap in time: say so and put the choice back
            QMessageBox.warning(self, "Dataset inputs", str(exc))
            self.refresh()


__all__ = ["DatasetInputsBar", "series_text"]
