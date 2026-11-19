"""Check boxes for picking which paper sources to query."""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QVBoxLayout, QWidget

from thesisagents.core.constants import ALL_SOURCES, DEFAULT_SOURCES
from thesisagents.gui.widgets.responsive import ReflowGrid


class SourceMultiselect(QWidget):
    """One check box per source, re-flowed into as many columns as fit.

    Defaults follow ``DEFAULT_SOURCES`` from core/constants.py: the
    opt-in sources (scholar, ieee scraping) are unchecked by default to
    match CLI behaviour. The boxes used to sit in a fixed three-column
    grid, which ran off the side pane in long-label locales and left
    blank space on a wide window. :class:`ReflowGrid` fits the columns
    to the width the pane actually has.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._boxes: dict[str, QCheckBox] = {}
        for name in ALL_SOURCES:
            box = QCheckBox(name)
            box.setChecked(name in DEFAULT_SOURCES)
            self._boxes[name] = box
        self._grid = ReflowGrid(list(self._boxes.values()), parent=self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._grid)

    def selected(self) -> tuple[str, ...]:
        return tuple(name for name, box in self._boxes.items() if box.isChecked())

    def set_selected(self, names: tuple[str, ...]) -> None:
        wanted = set(names)
        for name, box in self._boxes.items():
            box.setChecked(name in wanted)

    def grid(self) -> ReflowGrid:
        return self._grid
