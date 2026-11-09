"""Shot plan panel: build shots from characters and dialogue, and show how
the selected engines would make each one.

The plan comes from ``performance.planner.plan_shot`` against a live engine
registry, so an engine that is switched off, has no key, or cannot perform
the dialogue shows up as a blocker here. The only thing made from this panel
is dialogue audio, with each speaker's own voice; the shot's timing comes from
those recorded takes, never from estimates.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDoubleSpinBox, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPlainTextEdit, QPushButton,
    QSplitter, QVBoxLayout, QWidget)

from ..performance.engines import EngineRegistry, Role
from ..performance.planner import (
    EngineSelection, PlanContext, Shot, ShotPlan, pin_shot, plan_shot)
from ..performance import timing as tm
from . import performance_view as view


class ShotPlanPanel(QWidget):
    def __init__(self, project, registry: EngineRegistry,
                 on_changed: Optional[Callable[[], None]] = None,
                 voicer=None, audio_dir: Optional[Path] = None,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.project = project
        self.registry = registry
        # performance.voicing.DialogueVoicer; None hides nothing but disables
        # voicing with a reason.
        self.voicer = voicer
        self.audio_dir = audio_dir
        self.last_takes: list = []
        self._shown_line_ids: list[str] = []
        self._timing: Optional[tm.ShotTiming] = None
        self._on_changed = on_changed or (lambda: None)
        self._build()
        self.refresh()

    # -- layout --------------------------------------------------------------
    def _build(self) -> None:
        root = QHBoxLayout(self)
        split = QSplitter(Qt.Horizontal)
        root.addWidget(split)

        left = QWidget(); lv = QVBoxLayout(left)
        eng_box = QGroupBox("Engines"); ev = QVBoxLayout(eng_box)
        self.engine_combos: dict[str, QComboBox] = {}
        for key, role, label in (("video", Role.VIDEO, "Video"),
                                 ("voice", Role.VOICE, "Voice"),
                                 ("lipsync", Role.LIPSYNC, "Lip-sync")):
            row = QHBoxLayout(); row.addWidget(QLabel(label))
            combo = QComboBox()
            combo.currentIndexChanged.connect(lambda _i, k=key: self._engine_changed(k))
            self.engine_combos[key] = combo
            row.addWidget(combo, 1)
            ev.addLayout(row)
        lv.addWidget(eng_box)

        shot_box = QGroupBox("Shots"); sv = QVBoxLayout(shot_box)
        self.shot_list = QListWidget()
        self.shot_list.currentRowChanged.connect(lambda _r: self._show_shot())
        sv.addWidget(self.shot_list)
        sv.addWidget(QLabel("Characters in a new shot:"))
        self.cast_list = QListWidget()
        self.cast_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self.cast_list.setMaximumHeight(110)
        sv.addWidget(self.cast_list)
        r = QHBoxLayout()
        self.duration_spin = QDoubleSpinBox()
        self.duration_spin.setRange(1.0, 60.0); self.duration_spin.setValue(6.0)
        self.duration_spin.setSuffix(" s")
        self.add_shot_btn = QPushButton("Add shot")
        self.add_shot_btn.clicked.connect(self._add_shot)
        r.addWidget(self.duration_spin); r.addWidget(self.add_shot_btn)
        sv.addLayout(r)
        lv.addWidget(shot_box)
        split.addWidget(left)

        right = QWidget(); rv = QVBoxLayout(right)
        line_box = QGroupBox("Dialogue in this shot"); dv = QVBoxLayout(line_box)
        self.line_list = QListWidget()
        self.line_list.currentRowChanged.connect(lambda _r: self._update_line_buttons())
        dv.addWidget(self.line_list)
        r2 = QHBoxLayout()
        self.speaker_combo = QComboBox()
        self.line_edit = QLineEdit(); self.line_edit.setPlaceholderText("Spoken line")
        self.add_line_btn = QPushButton("Add line")
        self.add_line_btn.clicked.connect(self._add_line)
        self.line_edit.returnPressed.connect(self._add_line)
        r2.addWidget(self.speaker_combo); r2.addWidget(self.line_edit, 1)
        r2.addWidget(self.add_line_btn)
        dv.addLayout(r2)
        r3 = QHBoxLayout()
        self.revoice_btn = QPushButton("Re-voice selected line")
        self.revoice_btn.setToolTip("Records just this line again. Other lines' "
                                    "audio is not touched, and a failed retake "
                                    "keeps the previous take.")
        self.revoice_btn.clicked.connect(self._revoice_line)
        self.fit_btn = QPushButton("Fit shot to its lines")
        self.fit_btn.setToolTip("Sets the shot's length to what its recorded "
                                "lines need, with short pauses.")
        self.fit_btn.clicked.connect(self._fit_shot)
        r3.addWidget(self.revoice_btn); r3.addWidget(self.fit_btn)
        dv.addLayout(r3)
        self.timing_label = QLabel(""); self.timing_label.setWordWrap(True)
        dv.addWidget(self.timing_label)
        rv.addWidget(line_box, 1)

        plan_box = QGroupBox("Plan"); pv = QVBoxLayout(plan_box)
        # Read-only and scrollable: a plan can list many limitations, and a
        # fixed label clipped them.
        self.plan_text = QPlainTextEdit(); self.plan_text.setReadOnly(True)
        pv.addWidget(self.plan_text, 1)
        self.pin_btn = QPushButton("Pin current approved designs")
        self.pin_btn.setToolTip("Ties this shot to each character's current "
                                "approved design. Later re-approvals don't "
                                "change a pinned shot until you pin again.")
        self.pin_btn.clicked.connect(self._pin)
        pv.addWidget(self.pin_btn)
        self.voice_btn = QPushButton("Voice this shot's lines")
        self.voice_btn.setToolTip("Records each line with its speaker's own "
                                  "voice. Lines whose speaker has no installed "
                                  "voice are skipped and listed.")
        self.voice_btn.clicked.connect(self._voice_lines)
        pv.addWidget(self.voice_btn)
        self.voice_label = QLabel(""); self.voice_label.setWordWrap(True)
        pv.addWidget(self.voice_label)
        rv.addWidget(plan_box, 1)
        split.addWidget(right)

    # -- state ---------------------------------------------------------------
    def selection(self) -> EngineSelection:
        return self.project.engine_selection

    def timing_for(self, shot: Shot) -> tm.ShotTiming:
        return tm.shot_timing(shot, self.project.dialogue,
                              self.project.characters,
                              tm.read_manifest(self.audio_dir),
                              getattr(self.voicer, "scale_for", None))

    def current_line_id(self) -> Optional[str]:
        shot = self.current_shot()
        row = self.line_list.currentRow()
        if shot is None or row < 0:
            return None
        ids = self._shown_line_ids
        return ids[row] if row < len(ids) else None

    def current_shot(self) -> Optional[Shot]:
        row = self.shot_list.currentRow()
        shots = self.project.shots
        return shots[row] if 0 <= row < len(shots) else None

    def plan_for(self, shot: Shot) -> ShotPlan:
        ctx = PlanContext(characters=self.project.characters,
                          dialogue=self.project.dialogue,
                          selection=self.selection(),
                          language=getattr(self.project, "language", "en"))
        return plan_shot(shot, ctx, self.registry)

    def refresh(self, select_row: Optional[int] = None) -> None:
        self._fill_engines()
        self.cast_list.clear()
        self.speaker_combo.clear()
        for c in self.project.characters:
            self.cast_list.addItem(QListWidgetItem(c.name))
        keep = select_row if select_row is not None else self.shot_list.currentRow()
        self.shot_list.blockSignals(True)
        self.shot_list.clear()
        for s in self.project.shots:
            self.shot_list.addItem(view.shot_row(s, self.plan_for(s)))
        n = len(self.project.shots)
        self.shot_list.setCurrentRow(keep if 0 <= keep < n else (n - 1 if n else -1))
        self.shot_list.blockSignals(False)
        self._show_shot()

    def _fill_engines(self) -> None:
        sel = self.selection()
        for key, role in (("video", Role.VIDEO), ("voice", Role.VOICE),
                          ("lipsync", Role.LIPSYNC)):
            combo = self.engine_combos[key]
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("(none)", None)
            for e in self.registry.with_role(role):
                st = e.status()
                combo.addItem(e.name if st.available
                              else f"{e.name} (unavailable: {st.reason})", e.id)
            idx = combo.findData(getattr(sel, key))
            combo.setCurrentIndex(idx if idx >= 0 else 0)
            combo.blockSignals(False)

    def _show_shot(self) -> None:
        shot = self.current_shot()
        self.line_list.clear()
        self.speaker_combo.clear()
        for w in (self.add_line_btn, self.line_edit, self.speaker_combo, self.pin_btn):
            w.setEnabled(shot is not None)
        can_voice = bool(shot and shot.dialogue_line_ids and self.voicer
                         and self.audio_dir)
        self.voice_btn.setEnabled(can_voice)
        if self.voicer is None:
            self.voice_btn.setToolTip("Voicing isn't available in this view.")
        self._shown_line_ids = []
        self._timing = None
        if shot is None:
            self.plan_text.setPlainText("Add a shot to see its plan.")
            self.timing_label.setText("")
            self._update_line_buttons()
            return
        self._timing = self.timing_for(shot)
        per_line = {t.line_id: t for t in self._timing.lines}
        lines = {d.id: d for d in self.project.dialogue}
        for lid in shot.dialogue_line_ids:
            d = lines.get(lid)
            if d is not None:
                who = self.project.character(d.speaker_id)
                text = f"{who.name if who else d.speaker_id}: {d.text}"
                t = per_line.get(lid)
                if t is not None and self.audio_dir is not None:
                    text += tm.line_suffix(t)
                item = QListWidgetItem(text)
                if t is not None and t.reason:
                    item.setToolTip(t.reason)
                self.line_list.addItem(item)
                self._shown_line_ids.append(lid)
        self.timing_label.setText(tm.timing_text(self._timing)
                                  if self.audio_dir is not None else "")
        self._update_line_buttons()
        for cid in shot.character_ids:
            c = self.project.character(cid)
            if c is not None:
                self.speaker_combo.addItem(c.name, c.id)
        has_speaker = self.speaker_combo.count() > 0
        self.add_line_btn.setEnabled(has_speaker)
        self.line_edit.setEnabled(has_speaker)
        self.plan_text.setPlainText("\n".join(view.plan_lines(self.plan_for(shot))))

    def _update_line_buttons(self) -> None:
        self.revoice_btn.setEnabled(bool(
            self.voicer and self.audio_dir and self.current_line_id()))
        t = self._timing
        suggested = t.suggested_s() if t is not None else None
        self.fit_btn.setEnabled(suggested is not None
                                and abs(suggested - t.shot_s) >= 0.05)

    # -- actions -------------------------------------------------------------
    def _engine_changed(self, key: str) -> None:
        value = self.engine_combos[key].currentData()
        self.project.engine_selection = self.selection().model_copy(update={key: value})
        self.refresh()
        self._on_changed()

    def _replace_shot(self, shot: Shot) -> None:
        self.project.shots = [shot if s.id == shot.id else s for s in self.project.shots]
        self.project.touch()

    def _add_shot(self) -> None:
        rows = sorted(i.row() for i in self.cast_list.selectedIndexes())
        cast = [self.project.characters[r].id for r in rows]
        shot = Shot(id=view.new_shot_id(self.project.shots),
                    duration_s=self.duration_spin.value(), character_ids=cast)
        self.project.shots = self.project.shots + [shot]
        self.project.touch()
        self.cast_list.clearSelection()
        self.refresh(select_row=len(self.project.shots) - 1)
        self._on_changed()

    def _add_line(self) -> None:
        shot = self.current_shot()
        speaker = self.speaker_combo.currentData()
        if shot is None or not speaker:
            return
        try:
            line = view.new_line(self.project.dialogue, speaker, self.line_edit.text())
        except ValueError as exc:
            QMessageBox.warning(self, "Shot plan", str(exc))
            return
        self.project.dialogue = self.project.dialogue + [line]
        self._replace_shot(shot.model_copy(
            update={"dialogue_line_ids": shot.dialogue_line_ids + [line.id]}))
        self.line_edit.clear()
        self.refresh(select_row=self.shot_list.currentRow())
        self._on_changed()

    def _voice_lines(self) -> None:
        shot = self.current_shot()
        if shot is None:
            return
        self._record(shot.dialogue_line_ids)

    def _revoice_line(self) -> None:
        lid = self.current_line_id()
        if lid is not None:
            self._record([lid])

    def _record(self, line_ids: list[str]) -> None:
        if self.voicer is None or self.audio_dir is None:
            return
        keep_line = self.line_list.currentRow()
        from PySide6.QtWidgets import QApplication
        from ..performance.voicing import write_manifest
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            takes = self.voicer.voice_all(self.project.dialogue,
                                          self.project.characters,
                                          self.audio_dir,
                                          line_ids=line_ids)
            write_manifest(takes, self.audio_dir)
        finally:
            QApplication.restoreOverrideCursor()
        self.last_takes = takes
        done = [t for t in takes if t.ok]
        lines = [f"Voiced {len(done)} of {len(takes)} line(s)."]
        lines += [f"Not voiced: {t.message}" for t in takes if not t.ok]
        lines += [t.direction_note for t in takes if t.ok and t.direction_note]
        self.voice_label.setText("\n".join(lines))
        self._show_shot()
        if 0 <= keep_line < self.line_list.count():
            self.line_list.setCurrentRow(keep_line)

    def _fit_shot(self) -> None:
        shot = self.current_shot()
        t = self.timing_for(shot) if shot is not None else None
        suggested = t.suggested_s() if t is not None else None
        if suggested is None:
            return
        # The shot length control allows 1-60 s.
        suggested = min(max(suggested, 1.0), 60.0)
        self._replace_shot(shot.model_copy(update={"duration_s": suggested}))
        self.refresh(select_row=self.shot_list.currentRow())
        self._on_changed()

    def _pin(self) -> None:
        shot = self.current_shot()
        if shot is None:
            return
        self._replace_shot(pin_shot(shot, self.project.characters))
        self.refresh(select_row=self.shot_list.currentRow())
        self._on_changed()
