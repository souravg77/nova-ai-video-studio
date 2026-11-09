"""Locations (roadmap 7a): the places the script uses, with reference views.

Each location from the script's scene headings starts as a draft. Add a
frontal view (plus other angles and textures), approve it, and the animatic
uses the approved frontal view for shots in that place that have no approved
character. Approved views are locked until the location is unapproved.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from ..sheets.compose import render_location_sheet
from ..sheets.locations import (ALL_LOCATION_SLOTS, LABELS, LocationError,
                                approve_location, clear_location_view,
                                put_location, set_location_view,
                                unapprove_location)
from ..storage.asset_registry import safe_filename


class LocationsPanel(QWidget):
    def __init__(self, project, export_dir: Optional[Path] = None,
                 on_changed: Callable[[], None] = lambda: None) -> None:
        super().__init__()
        self.project = project
        self.export_dir = Path(export_dir) if export_dir else None
        self.on_changed = on_changed
        self._slot_paths: dict[str, QLabel] = {}
        self._slot_buttons: list[QPushButton] = []

        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.addWidget(QLabel("<b>Locations</b> (from the script's scene headings)"))
        self.list = QListWidget()
        self.list.currentRowChanged.connect(lambda _r: self._show())
        lv.addWidget(self.list, 1)
        split.addWidget(left)

        right = QWidget()
        rv = QVBoxLayout(right)
        self.title = QLabel()
        rv.addWidget(self.title)
        self.desc = QLineEdit()
        self.desc.setPlaceholderText("Description (time of day, mood, materials)")
        self.desc.editingFinished.connect(self._save_desc)
        rv.addWidget(self.desc)
        grid = QGridLayout()
        for r, slot in enumerate(ALL_LOCATION_SLOTS):
            grid.addWidget(QLabel(LABELS[slot]), r, 0)
            path = QLabel("empty")
            path.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self._slot_paths[slot] = path
            grid.addWidget(path, r, 1)
            choose = QPushButton("Choose image…")
            choose.clicked.connect(lambda _=False, s=slot: self._choose(s))
            clear = QPushButton("Clear")
            clear.clicked.connect(lambda _=False, s=slot: self.clear_slot(s))
            self._slot_buttons += [choose, clear]
            grid.addWidget(choose, r, 2)
            grid.addWidget(clear, r, 3)
        grid.setColumnStretch(1, 1)
        rv.addLayout(grid)
        btns = QHBoxLayout()
        self.approve_btn = QPushButton()
        self.approve_btn.clicked.connect(self.toggle_approval)
        self.sheet_btn = QPushButton("Export location sheet")
        self.sheet_btn.clicked.connect(self.export_sheet)
        btns.addWidget(self.approve_btn)
        btns.addStretch(1)
        btns.addWidget(self.sheet_btn)
        rv.addLayout(btns)
        self.status = QLabel()
        self.status.setWordWrap(True)
        rv.addWidget(self.status)
        rv.addStretch(1)
        split.addWidget(right)
        split.setSizes([280, 900])
        QVBoxLayout(self).addWidget(split)
        self.refresh()

    # ---- state --------------------------------------------------------------
    def current(self):
        row = self.list.currentRow()
        locs = self.project.director.locations
        return locs[row] if 0 <= row < len(locs) else None

    def refresh(self) -> None:
        row = max(0, self.list.currentRow())
        self.list.blockSignals(True)
        self.list.clear()
        for loc in self.project.director.locations:
            state = f"approved v{loc.version}" if loc.approved else "draft"
            self.list.addItem(QListWidgetItem(f"{loc.name}  [{state}]"))
        self.list.blockSignals(False)
        if self.project.director.locations:
            self.list.setCurrentRow(min(row, self.list.count() - 1))
        self._show()

    def _show(self) -> None:
        loc = self.current()
        has = loc is not None
        for w in (self.desc, self.approve_btn, self.sheet_btn, *self._slot_buttons):
            w.setEnabled(has)
        if not has:
            self.title.setText("Break down a script to list its locations.")
            self.desc.setText("")
            for lbl in self._slot_paths.values():
                lbl.setText("")
            return
        self.title.setText(f"<h3>{loc.name}</h3>")
        self.desc.setText(loc.description)
        self.desc.setReadOnly(loc.approved)
        for slot, lbl in self._slot_paths.items():
            p = loc.views.get(slot)
            lbl.setText(Path(p).name if p else "empty")
            lbl.setToolTip(p or "")
        for b in self._slot_buttons:
            b.setEnabled(not loc.approved)
        self.approve_btn.setText("Unapprove" if loc.approved else "Approve location")
        self.sheet_btn.setEnabled(self.export_dir is not None)

    def _replace(self, loc) -> None:
        put_location(self.project.director, loc)
        self.project.touch()
        self.refresh()
        self.on_changed()

    # ---- actions ------------------------------------------------------------
    def _save_desc(self) -> None:
        loc = self.current()
        if loc is not None and not loc.approved and self.desc.text() != loc.description:
            self._replace(loc.model_copy(update={"description": self.desc.text().strip()}))

    def _choose(self, slot: str) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, f"{LABELS[slot]} image", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            self.set_slot(slot, path)

    def set_slot(self, slot: str, path: str) -> bool:
        try:
            self._replace(set_location_view(self.current(), slot, path))
            self.status.setText(f"{LABELS[slot]} set.")
            return True
        except LocationError as exc:
            self.status.setText(str(exc))
            return False

    def clear_slot(self, slot: str) -> None:
        try:
            self._replace(clear_location_view(self.current(), slot))
        except LocationError as exc:
            self.status.setText(str(exc))

    def toggle_approval(self) -> None:
        loc = self.current()
        try:
            new = unapprove_location(loc) if loc.approved else approve_location(loc)
        except LocationError as exc:
            self.status.setText(str(exc))
            return
        self._replace(new)
        self.status.setText(f"{new.name} approved (v{new.version})." if new.approved
                            else f"{new.name} unapproved; its views can be changed.")

    def export_sheet(self) -> Optional[str]:
        loc = self.current()
        scenes = [s.heading for s in self.project.director.scenes
                  if s.location.strip().lower() == loc.name.strip().lower()]
        out = self.export_dir / f"{safe_filename(loc.name, 'location')}_sheet.png"
        rep = render_location_sheet(loc, out, scenes, self.project.name)
        self.status.setText(f"Sheet saved to {rep.path}"
                            + (f"\n{' '.join(rep.warnings)}" if rep.warnings else ""))
        return rep.path
