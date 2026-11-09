"""Scene builder: the chosen clip of every shot, in order, trimmed, exported.

Clips come from the Generate screen ("Use this version"). A shot without a
clip shows a still (its start frame or approved character design) or a
plain card, and the export says which shots those are.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDoubleSpinBox, QGroupBox, QHBoxLayout, QLabel, QListWidget, QMessageBox,
    QPushButton, QVBoxLayout, QWidget)

from ..generate.versions import VersionStore
from ..scene import sequence as sq
from ..scene.export import export_scene


class ScenePanel(QWidget):
    def __init__(self, project, generations_dir: Path, out_path: Callable[[], Path],
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.project = project
        self.versions = VersionStore(generations_dir)
        self.scene = sq.SceneStore(generations_dir)
        self._out_path = out_path
        self.cuts: list[sq.ResolvedCut] = []
        self._thread: Optional[threading.Thread] = None
        self._progress = ""
        self.last_export = None
        self._timer = QTimer(self); self._timer.setInterval(200)
        self._timer.timeout.connect(self._poll)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        box = QGroupBox("Scene"); bv = QVBoxLayout(box)
        self.cut_list = QListWidget()
        self.cut_list.currentRowChanged.connect(lambda _r: self._show_cut())
        bv.addWidget(self.cut_list, 1)
        r1 = QHBoxLayout()
        self.up_btn = QPushButton("Move up"); self.up_btn.clicked.connect(lambda: self._move(-1))
        self.down_btn = QPushButton("Move down"); self.down_btn.clicked.connect(lambda: self._move(1))
        self.play_btn = QPushButton("Play clip"); self.play_btn.clicked.connect(self._play)
        for b in (self.up_btn, self.down_btn, self.play_btn):
            r1.addWidget(b)
        bv.addLayout(r1)
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("Start at"))
        self.in_spin = QDoubleSpinBox(); self.in_spin.setDecimals(2); self.in_spin.setSuffix(" s")
        r2.addWidget(self.in_spin)
        r2.addWidget(QLabel("End at"))
        self.out_spin = QDoubleSpinBox(); self.out_spin.setDecimals(2); self.out_spin.setSuffix(" s")
        r2.addWidget(self.out_spin)
        self.trim_btn = QPushButton("Apply trim"); self.trim_btn.clicked.connect(self._trim)
        r2.addWidget(self.trim_btn)
        bv.addLayout(r2)
        self.detail = QLabel(""); self.detail.setWordWrap(True)
        bv.addWidget(self.detail)
        root.addWidget(box, 1)
        r3 = QHBoxLayout()
        self.total_label = QLabel("")
        self.export_btn = QPushButton("Export scene")
        self.export_btn.clicked.connect(self.export)
        self.open_btn = QPushButton("Play export")
        self.open_btn.clicked.connect(self._open_export)
        self.open_btn.setEnabled(False)
        r3.addWidget(self.total_label, 1); r3.addWidget(self.export_btn); r3.addWidget(self.open_btn)
        root.addLayout(r3)
        self.status = QLabel(""); self.status.setWordWrap(True)
        root.addWidget(self.status)

    # -- state ---------------------------------------------------------------
    def current(self) -> Optional[sq.ResolvedCut]:
        row = self.cut_list.currentRow()
        return self.cuts[row] if 0 <= row < len(self.cuts) else None

    def busy(self) -> bool:
        return self._thread is not None

    def refresh(self, select_shot: Optional[str] = None) -> None:
        keep = select_shot or (self.current().shot_id if self.current() else None)
        self.cuts = sq.resolve(self.project, self.versions, self.scene)
        self.cut_list.blockSignals(True)
        self.cut_list.clear()
        for i, c in enumerate(self.cuts, 1):
            self.cut_list.addItem(sq.cut_row(i, c))
        ids = [c.shot_id for c in self.cuts]
        self.cut_list.setCurrentRow(ids.index(keep) if keep in ids else (0 if ids else -1))
        self.cut_list.blockSignals(False)
        gaps = sum(1 for c in self.cuts if c.kind != sq.CLIP)
        self.total_label.setText(
            f"{len(self.cuts)} shot(s), {sq.total_s(self.cuts):g} s"
            + (f"; {gaps} without a clip yet" if gaps else ""))
        self.export_btn.setEnabled(bool(self.cuts) and gaps < len(self.cuts) and not self.busy())
        self.export_btn.setToolTip("" if gaps < len(self.cuts) else
                                   "Choose at least one clip on the Generate screen first.")
        self._show_cut()

    def _show_cut(self) -> None:
        c = self.current()
        row = self.cut_list.currentRow()
        self.up_btn.setEnabled(c is not None and row > 0)
        self.down_btn.setEnabled(c is not None and row < len(self.cuts) - 1)
        is_clip = bool(c and c.kind == sq.CLIP)
        for w in (self.in_spin, self.out_spin, self.trim_btn, self.play_btn):
            w.setEnabled(is_clip)
        if c is None:
            self.detail.setText("Add shots in the shot plan first.")
            return
        if is_clip:
            v = self.versions.get(c.version_id)
            length = float(v.duration_s or 0.0)
            for s in (self.in_spin, self.out_spin):
                s.setRange(0.0, length)
            self.in_spin.setValue(c.in_s); self.out_spin.setValue(c.out_s)
            self.detail.setText(f"Clip {length:.2f} s long. Prompt: {v.prompt}")
        else:
            self.detail.setText(c.note + (" Showing its start frame or approved "
                                          "character design." if c.kind == sq.STILL
                                          else " Showing a plain card."))

    # -- actions -------------------------------------------------------------
    def _move(self, delta: int) -> None:
        c = self.current()
        if c is not None:
            self.scene.move(self.project, c.shot_id, delta)
            self.refresh(select_shot=c.shot_id)

    def _trim(self) -> bool:
        c = self.current()
        if c is None or c.kind != sq.CLIP:
            return False
        try:
            self.scene.set_trim(c.shot_id, self.versions.get(c.version_id),
                                self.in_spin.value(), self.out_spin.value())
        except ValueError as exc:
            QMessageBox.warning(self, "Scene", str(exc))
            return False
        self.refresh(select_shot=c.shot_id)
        return True

    def _play(self) -> None:
        c = self.current()
        if c is not None and c.kind == sq.CLIP:
            QDesktopServices.openUrl(QUrl.fromLocalFile(c.source))

    def export(self) -> bool:
        if not self.export_btn.isEnabled():
            return False
        cuts, out = list(self.cuts), self._out_path()
        self._progress = "Starting"
        self.last_export = None

        def work():
            self.last_export = export_scene(cuts, out, progress=self._set_progress)

        self._thread = threading.Thread(target=work, daemon=True)
        self._thread.start()
        self.export_btn.setEnabled(False)
        self._timer.start()
        return True

    def _set_progress(self, msg: str) -> None:
        self._progress = msg

    def _poll(self) -> None:
        self.status.setText(self._progress)
        if self._thread is None or self._thread.is_alive():
            return
        self._thread = None
        self._timer.stop()
        r = self.last_export
        if r is None:
            self.status.setText("The export stopped unexpectedly.")
        elif r.ok:
            self.status.setText(f"{r.message}\nSaved to {r.path}")
        else:
            self.status.setText(f"Not exported: {r.message}")
        self.open_btn.setEnabled(bool(r and r.ok))
        self.refresh()

    def wait(self, timeout_s: float = 120.0) -> None:
        if self._thread is not None:
            self._thread.join(timeout_s)
        self._poll()

    def _open_export(self) -> None:
        if self.last_export and self.last_export.ok:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.last_export.path))
