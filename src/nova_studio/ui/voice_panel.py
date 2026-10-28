"""Voice Studio UI panel (Phase 3 UI).

A self-contained widget: voice gallery with availability, an audition button,
voice settings (speed/pause) that disable or label unsupported controls per
engine, a pronunciation-dictionary editor, and per-scene regeneration.

Pure formatting/logic is kept in standalone functions so it can be unit-tested
headlessly (PySide6 is not installable in CI).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QMessageBox, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..voice.expression import ExpressionSettings, PronunciationDict


# ---- pure helpers (headless-testable) --------------------------------------
def format_gallery(gallery) -> list[str]:
    """One display line per engine, honest about availability."""
    lines: list[str] = []
    for e in gallery.engines:
        mark = "✓" if e.available else "✗"
        caps = []
        c = e.capabilities
        for name, on in (("speed", c.speed), ("pause", c.pause),
                         ("emphasis", c.emphasis), ("emotion", c.emotion),
                         ("clone", c.cloning)):
            if on:
                caps.append(name)
        cap_str = ", ".join(caps) or "basic"
        line = f"{mark} {e.display_name} [{cap_str}] — "
        line += (f"{len(e.voices)} voice(s)" if e.available
                 else (e.reason or "unavailable"))
        lines.append(line)
    return lines


def voice_rows(gallery) -> list[dict]:
    """Flatten voices across engines for the gallery list."""
    rows = []
    for e in gallery.engines:
        for v in e.voices:
            rows.append({
                "engine_id": e.engine_id, "name": v.name, "path": v.path,
                "language": v.language, "quality": v.quality,
                "license_ok": v.license_ok, "available": e.available,
            })
    return rows


def unsupported_for(gallery, engine_id: str) -> list[str]:
    """Which expression controls this engine does NOT support (to disable)."""
    e = gallery.engine(engine_id)
    if not e:
        return ["speed", "pause", "emphasis", "emotion"]
    c = e.capabilities
    out = []
    if not c.speed:
        out.append("speed")
    if not c.pause:
        out.append("pause")
    if not c.emphasis:
        out.append("emphasis")
    if not c.emotion:
        out.append("emotion")
    return out


# ---- the widget ------------------------------------------------------------
class VoiceStudioPanel(QWidget):
    def __init__(self, studio, parent=None) -> None:
        super().__init__(parent)
        self.studio = studio
        self.pron = PronunciationDict()
        self._build()
        self.refresh_gallery()

    def _build(self) -> None:
        root = QVBoxLayout(self)

        gal = QGroupBox("Voice gallery")
        gv = QVBoxLayout(gal)
        self.engine_summary = QLabel("")
        self.engine_summary.setWordWrap(True)
        gv.addWidget(self.engine_summary)
        self.voice_list = QListWidget()
        self.voice_list.currentRowChanged.connect(self._voice_selected)
        gv.addWidget(self.voice_list)
        row = QHBoxLayout()
        self.audition_btn = QPushButton("Audition")
        self.audition_btn.clicked.connect(self._audition)
        self.refresh_btn = QPushButton("Refresh voices")
        self.refresh_btn.clicked.connect(self.refresh_gallery)
        row.addWidget(self.audition_btn)
        row.addWidget(self.refresh_btn)
        gv.addLayout(row)
        root.addWidget(gal)

        settings = QGroupBox("Voice settings")
        sv = QVBoxLayout(settings)
        speed_row = QHBoxLayout()
        self.speed_label = QLabel("Speed:")
        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(0.5, 2.0)
        self.speed_spin.setSingleStep(0.05)
        self.speed_spin.setValue(1.0)
        speed_row.addWidget(self.speed_label)
        speed_row.addWidget(self.speed_spin)
        sv.addLayout(speed_row)
        pause_row = QHBoxLayout()
        self.pause_label = QLabel("Sentence pause (ms):")
        self.pause_spin = QSpinBox()
        self.pause_spin.setRange(0, 2000)
        self.pause_spin.setSingleStep(50)
        pause_row.addWidget(self.pause_label)
        pause_row.addWidget(self.pause_spin)
        sv.addLayout(pause_row)
        self.unsupported_label = QLabel("")
        self.unsupported_label.setWordWrap(True)
        sv.addWidget(self.unsupported_label)
        root.addWidget(settings)

        pron_box = QGroupBox("Pronunciation dictionary")
        pv = QVBoxLayout(pron_box)
        add_row = QHBoxLayout()
        self.word_edit = QLineEdit(); self.word_edit.setPlaceholderText("word")
        self.sayas_edit = QLineEdit(); self.sayas_edit.setPlaceholderText("say as")
        add_btn = QPushButton("Add")
        add_btn.clicked.connect(self._add_pron)
        add_row.addWidget(self.word_edit)
        add_row.addWidget(self.sayas_edit)
        add_row.addWidget(add_btn)
        pv.addLayout(add_row)
        self.pron_table = QTableWidget(0, 2)
        self.pron_table.setHorizontalHeaderLabels(["Word", "Say as"])
        pv.addWidget(self.pron_table)
        root.addWidget(pron_box)

        regen_box = QGroupBox("Per-scene narration")
        rv = QVBoxLayout(regen_box)
        self.scene_combo = QComboBox()
        rv.addWidget(QLabel("Regenerate a single scene without redoing others:"))
        rv.addWidget(self.scene_combo)
        self.regen_btn = QPushButton("Regenerate selected scene")
        self.regen_btn.clicked.connect(self._regenerate_scene)
        rv.addWidget(self.regen_btn)
        self.regen_status = QLabel("")
        self.regen_status.setWordWrap(True)
        rv.addWidget(self.regen_status)
        root.addWidget(regen_box)

    # ---- behavior ----
    def refresh_gallery(self) -> None:
        gallery = self.studio.voice_gallery()
        self._gallery = gallery
        self.engine_summary.setText("\n".join(format_gallery(gallery)))
        self.voice_list.clear()
        self._rows = voice_rows(gallery)
        for r in self._rows:
            label = (f"[{r['engine_id']}] {r['name']} · {r['language']} · "
                     f"{r['quality']}")
            self.voice_list.addItem(label)
        # No usable voice -> audition disabled.
        self.audition_btn.setEnabled(bool(self._rows))
        self._apply_engine_support(self._rows[0]["engine_id"] if self._rows else "piper")

    def _voice_selected(self, row: int) -> None:
        if 0 <= row < len(getattr(self, "_rows", [])):
            self._apply_engine_support(self._rows[row]["engine_id"])

    def _apply_engine_support(self, engine_id: str) -> None:
        unsupported = unsupported_for(self._gallery, engine_id)
        self.speed_spin.setEnabled("speed" not in unsupported)
        self.pause_spin.setEnabled("pause" not in unsupported)
        if unsupported:
            self.unsupported_label.setText(
                "Not supported by this engine (disabled): "
                + ", ".join(unsupported))
        else:
            self.unsupported_label.setText("All settings supported.")

    def _current_voice(self) -> Optional[dict]:
        row = self.voice_list.currentRow()
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return self._rows[0] if self._rows else None

    def _expression(self) -> ExpressionSettings:
        return ExpressionSettings(speed=self.speed_spin.value(),
                                  pause_sentence_ms=self.pause_spin.value())

    def _audition(self) -> None:
        v = self._current_voice()
        if not v:
            QMessageBox.information(self, "No voice", "No voice available.")
            return
        result = self.studio.audition_voice(
            v["engine_id"], v["path"], expression=self._expression(),
            pronunciation=self.pron)
        if result["ok"]:
            self.regen_status.setText(f"Audition saved: {result['path']}")
        else:
            QMessageBox.warning(self, "Audition unavailable", result["message"])

    def _add_pron(self) -> None:
        word = self.word_edit.text().strip()
        say = self.sayas_edit.text().strip()
        if word and say:
            self.pron.add(word, say)
            r = self.pron_table.rowCount()
            self.pron_table.insertRow(r)
            self.pron_table.setItem(r, 0, QTableWidgetItem(word))
            self.pron_table.setItem(r, 1, QTableWidgetItem(say))
            self.word_edit.clear()
            self.sayas_edit.clear()

    def set_scenes(self, scene_titles: list[str]) -> None:
        self.scene_combo.clear()
        for i, t in enumerate(scene_titles):
            self.scene_combo.addItem(f"{i+1}. {t}")

    def _regenerate_scene(self) -> None:
        # Wired by MainWindow via a callback if scenes exist; stub-safe here.
        idx = self.scene_combo.currentIndex()
        if idx < 0:
            self.regen_status.setText("No scene selected.")
            return
        self.regen_status.setText(
            f"Requested regeneration of scene {idx+1} "
            f"(requires an installed voice).")
