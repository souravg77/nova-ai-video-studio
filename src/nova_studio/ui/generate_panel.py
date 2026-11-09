"""Generate screen: make versions of a shot with the selected video engine.

Modes: text, start/end frames, or the shot's approved characters. Several
versions can be asked for at once; every version (and every failed attempt,
with its reason) is kept, and one is chosen per shot. A frame of any version
can become the next shot's start frame, for continuity between shots.

Cloud generation is never silent: the button says why it is unavailable,
and each press first states what will be sent and billed, and waits for a
yes. Nothing is faked: a version exists only if a playable file arrived.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
    QSpinBox, QSplitter, QVBoxLayout, QWidget)

from ..adapters.gemini_omni import RESOLUTIONS
from ..generate import request as gr
from ..generate.extend import can_extend, extend_version
from ..generate.frames import save_frame
from ..generate.runner import run_generation
from ..generate.versions import VersionStore
from . import performance_view as view


def version_row(v, chosen_id: Optional[str]) -> str:
    when = v.created_at[:16].replace("T", " ")
    if not v.ok:
        return f"{when}  failed: {v.message}"
    tags = [gr.MODE_LABELS.get(v.mode, v.mode)]
    if v.duration_s:
        tags.append(f"{v.duration_s:.1f} s")
    tags.append("with sound" if v.has_audio else "no sound")
    if not v.usable:
        tags.append("FILE MISSING")
    mark = "CHOSEN  " if v.id == chosen_id else ""
    return f"{mark}{when}  {', '.join(tags)}"


class GeneratePanel(QWidget):
    def __init__(self, project, engine=None, generations_dir: Optional[Path] = None,
                 on_changed: Optional[Callable[[], None]] = None,
                 confirm: Optional[Callable[[str], bool]] = None,
                 engines: Optional[list] = None,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.project = project
        # Video engines with status(), spec() and generate(), such as
        # adapters.gemini_omni.GeminiOmniEngine. The user picks one; NOVA
        # never switches engines (local or cloud) on its own.
        self.engines = list(engines) if engines is not None else (
            [engine] if engine is not None else [])
        self.store = VersionStore(generations_dir) if generations_dir else None
        self._on_changed = on_changed or (lambda: None)
        self._confirm = confirm or self._ask
        self._prompts: dict[str, str] = {}
        self._thread: Optional[threading.Thread] = None
        self._cancel = threading.Event()
        self._progress = ""
        self._result: Optional[tuple] = None
        self._timer = QTimer(self); self._timer.setInterval(200)
        self._timer.timeout.connect(self._poll)
        self._build()
        self.refresh()

    # -- layout --------------------------------------------------------------
    def _build(self) -> None:
        root = QHBoxLayout(self)
        split = QSplitter(Qt.Horizontal); root.addWidget(split)

        left = QWidget(); lv = QVBoxLayout(left)
        shots = QGroupBox("Shot"); sv = QVBoxLayout(shots)
        self.shot_list = QListWidget()
        self.shot_list.currentRowChanged.connect(lambda _r: self._show_shot())
        sv.addWidget(self.shot_list)
        lv.addWidget(shots, 1)

        req = QGroupBox("Request"); rv = QVBoxLayout(req)
        self.engine_combo = QComboBox()
        for e in self.engines:
            self.engine_combo.addItem(e.spec().name)
        self.engine_combo.currentIndexChanged.connect(lambda _i: self._engine_changed())
        rv.addWidget(self.engine_combo)
        self.mode_combo = QComboBox()
        for m in gr.MODES:
            self.mode_combo.addItem(gr.MODE_LABELS[m], m)
        self.mode_combo.currentIndexChanged.connect(lambda _i: self._update())
        rv.addWidget(self.mode_combo)
        self.mention_combo = QComboBox()
        self.mention_combo.setToolTip("Insert @Name: that character's approved "
                                      "design goes along as a reference.")
        self.mention_combo.activated.connect(self._insert_mention)
        rv.addWidget(self.mention_combo)
        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setPlaceholderText(
            "Describe the shot: who, what happens, where, camera, light, sound.")
        self.prompt_edit.textChanged.connect(self._prompt_changed)
        rv.addWidget(self.prompt_edit, 1)
        self.frame_btns = {}
        for key, label in (("start_frame", "Start frame"), ("end_frame", "End frame")):
            row = QHBoxLayout()
            lab = QLabel(f"{label}: none"); lab.setWordWrap(True)
            pick = QPushButton("Choose…")
            pick.clicked.connect(lambda _c=False, k=key: self._pick_frame(k))
            clear = QPushButton("Clear")
            clear.clicked.connect(lambda _c=False, k=key: self.set_frame(k, None))
            row.addWidget(lab, 1); row.addWidget(pick); row.addWidget(clear)
            rv.addLayout(row)
            self.frame_btns[key] = (lab, pick, clear)
        opts = QHBoxLayout()
        self.aspect_combo = QComboBox()
        self.res_combo = QComboBox()
        self.dur_spin = QDoubleSpinBox()
        self.dur_spin.setSuffix(" s"); self.dur_spin.setDecimals(1)
        self.out_spin = QSpinBox(); self.out_spin.setRange(1, gr.MAX_OUTPUTS)
        self.out_spin.setSuffix(" version(s)")
        for w in (self.aspect_combo, self.res_combo):
            w.currentIndexChanged.connect(lambda _i: self._update())
        for w in (self.dur_spin, self.out_spin):
            w.valueChanged.connect(lambda _v: self._update())
        for w in (self.aspect_combo, self.res_combo, self.dur_spin, self.out_spin):
            opts.addWidget(w)
        rv.addLayout(opts)
        self.usage_label = QLabel(""); self.usage_label.setWordWrap(True)
        rv.addWidget(self.usage_label)
        self.blocker_label = QLabel(""); self.blocker_label.setWordWrap(True)
        rv.addWidget(self.blocker_label)
        brow = QHBoxLayout()
        self.generate_btn = QPushButton("Generate")
        self.generate_btn.clicked.connect(self.generate)
        self.stop_btn = QPushButton("Stop after this version")
        self.stop_btn.clicked.connect(self._cancel.set)
        self.stop_btn.setEnabled(False)
        brow.addWidget(self.generate_btn); brow.addWidget(self.stop_btn)
        rv.addLayout(brow)
        self.progress_label = QLabel(""); self.progress_label.setWordWrap(True)
        rv.addWidget(self.progress_label)
        lv.addWidget(req, 2)
        split.addWidget(left)
        self._fill_engine_options()

        right = QWidget(); gv = QVBoxLayout(right)
        vbox = QGroupBox("Versions of this shot"); vv = QVBoxLayout(vbox)
        self.version_list = QListWidget()
        self.version_list.currentRowChanged.connect(lambda _r: self._update_version_buttons())
        vv.addWidget(self.version_list, 1)
        r1 = QHBoxLayout()
        self.choose_btn = QPushButton("Use this version")
        self.choose_btn.clicked.connect(self._choose)
        self.open_btn = QPushButton("Play")
        self.open_btn.clicked.connect(self._open)
        r1.addWidget(self.choose_btn); r1.addWidget(self.open_btn)
        vv.addLayout(r1)
        r2 = QHBoxLayout()
        self.frame_at = QDoubleSpinBox(); self.frame_at.setRange(0.0, 600.0)
        self.frame_at.setDecimals(2); self.frame_at.setSuffix(" s")
        self.next_start_btn = QPushButton("Use this frame as the next shot's start")
        self.next_start_btn.clicked.connect(self._frame_to_next_shot)
        r2.addWidget(self.frame_at); r2.addWidget(self.next_start_btn, 1)
        vv.addLayout(r2)
        ext = QGroupBox("Extend this version (longer shot)"); xv = QVBoxLayout(ext)
        self.extend_prompt = QLineEdit()
        self.extend_prompt.setPlaceholderText("How does the action continue?")
        self.extend_prompt.textChanged.connect(lambda _t: self._update_version_buttons())
        xv.addWidget(self.extend_prompt)
        r3 = QHBoxLayout()
        self.extend_spin = QDoubleSpinBox(); self.extend_spin.setRange(3.0, 10.0)
        self.extend_spin.setValue(6.0); self.extend_spin.setSuffix(" s more")
        self.extend_btn = QPushButton("Extend")
        self.extend_btn.clicked.connect(self.extend)
        r3.addWidget(self.extend_spin); r3.addWidget(self.extend_btn, 1)
        xv.addLayout(r3)
        vv.addWidget(ext)
        self.version_detail = QLabel(""); self.version_detail.setWordWrap(True)
        vv.addWidget(self.version_detail)
        gv.addWidget(vbox)
        split.addWidget(right)

    # -- engine --------------------------------------------------------------
    @property
    def engine(self):
        i = self.engine_combo.currentIndex()
        return self.engines[i] if 0 <= i < len(self.engines) else None

    def caps(self):
        from ..adapters.gemini_omni import CAPABILITIES
        e = self.engine
        return e.spec().capabilities if e is not None else CAPABILITIES

    def _fill_engine_options(self) -> None:
        caps, e = self.caps(), self.engine
        keep_a, keep_r = self.aspect_combo.currentData(), self.res_combo.currentData()
        for combo in (self.aspect_combo, self.res_combo):
            combo.blockSignals(True); combo.clear()
        for a in caps.aspect_ratios or ("16:9",):
            self.aspect_combo.addItem(a, a)
        for r in getattr(e, "resolutions", None) or RESOLUTIONS:
            self.res_combo.addItem(r, r)
        for combo, keep, default in ((self.aspect_combo, keep_a, None),
                                     (self.res_combo, keep_r, "720p")):
            i = combo.findData(keep)
            if i < 0:
                i = combo.findData(default) if default else 0
            combo.setCurrentIndex(max(i, 0))
            combo.blockSignals(False)
        self.dur_spin.blockSignals(True)
        self.dur_spin.setRange(caps.min_duration_s or 1.0, caps.max_duration_s or 10.0)
        self.dur_spin.blockSignals(False)

    def _engine_changed(self) -> None:
        self._fill_engine_options()
        self._show_shot()

    # -- state ---------------------------------------------------------------
    def current_shot(self):
        row = self.shot_list.currentRow()
        shots = self.project.shots
        return shots[row] if 0 <= row < len(shots) else None

    def spec(self) -> Optional[gr.GenerateSpec]:
        shot = self.current_shot()
        if shot is None:
            return None
        return gr.GenerateSpec(
            shot_id=shot.id, mode=self.mode_combo.currentData(),
            prompt=self.prompt_edit.toPlainText(), outputs=self.out_spin.value(),
            aspect_ratio=self.aspect_combo.currentData(),
            resolution=self.res_combo.currentData(),
            duration_s=self.dur_spin.value())

    def _versions(self) -> list:
        shot = self.current_shot()
        if shot is None or self.store is None:
            return []
        return list(reversed(self.store.versions(shot.id)))   # newest first

    def current_version(self):
        row = self.version_list.currentRow()
        vs = self._versions()
        return vs[row] if 0 <= row < len(vs) else None

    def busy(self) -> bool:
        return self._thread is not None

    # -- refresh -------------------------------------------------------------
    def refresh(self) -> None:
        keep = self.shot_list.currentRow()
        self.shot_list.blockSignals(True)
        self.shot_list.clear()
        for s in self.project.shots:
            chosen = self.store.chosen(s.id) if self.store else None
            self.shot_list.addItem(f"{s.id}: {s.duration_s:g} s"
                                   + (", clip chosen" if chosen else ""))
        n = len(self.project.shots)
        self.shot_list.setCurrentRow(keep if 0 <= keep < n else (0 if n else -1))
        self.shot_list.blockSignals(False)
        self._show_shot()

    def _fill_mentions(self) -> None:
        self.mention_combo.blockSignals(True)
        self.mention_combo.clear()
        self.mention_combo.addItem("Mention a character…", None)
        for c in self.project.characters:
            self.mention_combo.addItem(f"@{c.name}" + ("" if c.approved else
                                                       " (not approved)"), c.name)
        self.mention_combo.setCurrentIndex(0)
        self.mention_combo.blockSignals(False)

    def _insert_mention(self, index: int) -> None:
        name = self.mention_combo.itemData(index)
        if name:
            self.prompt_edit.insertPlainText(f"@{name} ")
            self.prompt_edit.setFocus()
        self.mention_combo.setCurrentIndex(0)

    def _show_shot(self) -> None:
        self._fill_mentions()
        shot = self.current_shot()
        self.prompt_edit.blockSignals(True)
        self.prompt_edit.setPlainText(self._prompts.get(shot.id, "") if shot else "")
        self.prompt_edit.blockSignals(False)
        if shot is not None:
            self.dur_spin.blockSignals(True)
            self.dur_spin.setValue(min(max(shot.duration_s, self.dur_spin.minimum()),
                                       self.dur_spin.maximum()))
            self.dur_spin.blockSignals(False)
        self._show_versions()
        self._update()

    def _show_versions(self) -> None:
        shot = self.current_shot()
        chosen = self.store.chosen(shot.id) if (shot and self.store) else None
        self.version_list.blockSignals(True)
        self.version_list.clear()
        for v in self._versions():
            item = QListWidgetItem(version_row(v, chosen.id if chosen else None))
            item.setToolTip(v.prompt)
            self.version_list.addItem(item)
        if self.version_list.count():
            self.version_list.setCurrentRow(0)
        self.version_list.blockSignals(False)
        self._update_version_buttons()

    def _update(self) -> None:
        shot = self.current_shot()
        frames_mode = self.mode_combo.currentData() == "frames"
        for key, (lab, pick, clear) in self.frame_btns.items():
            p = getattr(shot, key, None) if shot else None
            title = "Start frame" if key == "start_frame" else "End frame (optional)"
            lab.setText(f"{title}: {Path(p).name if p else 'none'}")
            pick.setEnabled(bool(shot) and frames_mode and not self.busy())
            clear.setEnabled(bool(shot and p) and frames_mode and not self.busy())
        spec = self.spec()
        reasons = []
        if spec is None:
            reasons.append("Add a shot in the shot plan first.")
        if self.store is None:
            reasons.append("Generation isn't available in this view.")
        e = self.engine
        if e is None:
            reasons.append("No video engine is set up.")
        else:
            st = e.status()
            if not st.available:
                reasons.append(f"{e.spec().name} is unavailable: {st.reason}.")
        warnings = []
        if spec is not None:
            prep = gr.prepare(spec, self.project, self.caps())
            reasons += prep.blockers
            warnings = prep.warnings
            self.usage_label.setText(self._usage(spec))
        else:
            self.usage_label.setText("")
        self.blocker_label.setText("\n".join(
            [f"Can't generate yet: {r}" for r in reasons]
            + [f"Warning: {w}" for w in warnings]))
        self.generate_btn.setEnabled(not reasons and not self.busy())
        self.mode_combo.setEnabled(not self.busy())
        self.engine_combo.setEnabled(not self.busy() and len(self.engines) > 1)

    def _update_version_buttons(self) -> None:
        v = self.current_version()
        shot = self.current_shot()
        chosen = self.store.chosen(shot.id) if (shot and self.store) else None
        usable = bool(v and v.usable)
        self.choose_btn.setEnabled(usable and not (chosen and chosen.id == v.id))
        self.open_btn.setEnabled(usable)
        has_next = bool(shot) and self._next_shot(shot) is not None
        self.next_start_btn.setEnabled(usable and has_next)
        why = can_extend(v)
        omni = next((e for e in self.engines
                     if e.spec().id == (v.engine_id if v else None)), None)
        if why is None and omni is None:
            why = "That clip's engine isn't set up here."
        elif why is None and not omni.status().available:
            why = f"{omni.spec().name} is unavailable: {omni.status().reason}."
        elif why is None and not self.extend_prompt.text().strip():
            why = "Describe how the action continues."
        self.extend_btn.setEnabled(why is None and not self.busy())
        self.extend_btn.setToolTip(why or "")
        self.next_start_btn.setToolTip("" if has_next else "This is the last shot.")
        if v is not None and v.duration_s:
            self.frame_at.setMaximum(max(v.duration_s - 0.05, 0.0))
        if v is None:
            self.version_detail.setText("No versions yet." if shot else "")
        else:
            self.version_detail.setText(
                f"Prompt: {v.prompt}\n{v.message}"
                + (f"\n{v.width}x{v.height}, {v.engine_id}"
                   + (f" ({v.model})" if v.model else "")
                   + (", SynthID watermark" if v.engine_id == "gemini-omni-flash" else "")
                   if v.ok and v.width else ""))

    # -- actions -------------------------------------------------------------
    def _prompt_changed(self) -> None:
        shot = self.current_shot()
        if shot is not None:
            self._prompts[shot.id] = self.prompt_edit.toPlainText()
        self._update()

    def _replace_shot(self, shot) -> None:
        self.project.shots = [shot if s.id == shot.id else s for s in self.project.shots]
        self.project.touch()

    def _frames_dir(self) -> Optional[Path]:
        return self.store.root / "frames" if self.store else None

    def set_frame(self, key: str, path: Optional[Path]) -> bool:
        shot = self.current_shot()
        if shot is None:
            return False
        stored = None
        if path is not None:
            try:
                stored = str(view.copy_into_project(Path(path), self._frames_dir(),
                                                    f"{shot.id}-{key}"))
            except ValueError as exc:
                QMessageBox.warning(self, "Generate", str(exc))
                return False
        self._replace_shot(shot.model_copy(update={key: stored}))
        self._update()
        self._on_changed()
        return True

    def _pick_frame(self, key: str) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Choose a frame image", "",
                                           "Images (*.png *.jpg *.jpeg)")
        if f:
            self.set_frame(key, Path(f))

    def _ask(self, text: str) -> bool:
        return QMessageBox.question(
            self, "Send to Google?", text + "\n\nSend it?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes

    def _usage(self, spec) -> str:
        e = self.engine
        if e is None:
            return ""
        return gr.usage_text(spec, e.spec().name, self.caps().is_cloud)

    def generate(self) -> bool:
        spec = self.spec()
        if spec is None or not self.generate_btn.isEnabled():
            return False
        # Anything that leaves this PC needs a yes every time.
        if self.caps().is_cloud and not self._confirm(self._usage(spec)):
            self.progress_label.setText("Not sent.")
            return False
        engine = self.engine
        self._cancel.clear()
        self._result = None
        self._progress = "Starting"

        def work():
            try:
                vs = run_generation(engine, spec, self.project, self.store,
                                    on_progress=self._set_progress, cancel=self._cancel)
                self._result = ("ok", vs)
            except Exception as exc:          # reported to the user, never hidden
                self._result = ("error", str(exc))

        self._thread = threading.Thread(target=work, daemon=True)
        self._thread.start()
        self.stop_btn.setEnabled(spec.outputs > 1)
        self._update()
        self._timer.start()
        return True

    def extend(self) -> bool:
        v = self.current_version()
        if v is None or not self.extend_btn.isEnabled():
            return False
        engine = next(e for e in self.engines if e.spec().id == v.engine_id)
        secs = self.extend_spin.value()
        text = (f"This sends 1 request to Google ({engine.spec().name}, cloud) to "
                f"continue this clip by about {secs:g} s at {v.resolution or '720p'}: "
                f"about {secs:g} s of video billed to your Gemini API key. "
                f"Google sets the price; NOVA can't see your bill.")
        if not self._confirm(text):
            self.progress_label.setText("Not sent.")
            return False
        prompt = self.extend_prompt.text()
        self._result = None
        self._progress = "Starting"

        def work():
            try:
                nv = extend_version(engine, v, prompt, secs, self.store,
                                    on_progress=self._set_progress)
                self._result = ("ok", [nv])
            except Exception as exc:
                self._result = ("error", str(exc))

        self._thread = threading.Thread(target=work, daemon=True)
        self._thread.start()
        self._update(); self._update_version_buttons()
        self._timer.start()
        return True

    def _set_progress(self, msg: str) -> None:
        self._progress = msg

    def _poll(self) -> None:
        self.progress_label.setText(self._progress)
        if self._thread is None or self._thread.is_alive():
            return
        self._thread = None
        self._timer.stop()
        self.stop_btn.setEnabled(False)
        kind, payload = self._result or ("error", "The generation stopped unexpectedly.")
        if kind == "error":
            self.progress_label.setText(f"Not generated: {payload}")
        else:
            good = [v for v in payload if v.ok]
            lines = [f"{len(good)} of {len(payload)} version(s) generated."]
            lines += [f"Failed: {v.message}" for v in payload if not v.ok]
            self.progress_label.setText("\n".join(lines))
        self.refresh()

    def wait(self, timeout_s: float = 30.0) -> None:
        """Block until a running generation finishes (used by tests)."""
        if self._thread is not None:
            self._thread.join(timeout_s)
        self._poll()

    def _choose(self) -> None:
        v, shot = self.current_version(), self.current_shot()
        if v is None or shot is None or self.store is None:
            return
        try:
            self.store.choose(shot.id, v.id)
        except ValueError as exc:
            QMessageBox.warning(self, "Generate", str(exc))
            return
        self.refresh()
        self._on_changed()

    def _open(self) -> None:
        v = self.current_version()
        if v is not None and v.usable:
            QDesktopServices.openUrl(QUrl.fromLocalFile(v.path))

    def _next_shot(self, shot):
        ids = [s.id for s in self.project.shots]
        i = ids.index(shot.id) if shot.id in ids else -1
        return self.project.shots[i + 1] if 0 <= i < len(ids) - 1 else None

    def _frame_to_next_shot(self) -> bool:
        v, shot = self.current_version(), self.current_shot()
        nxt = self._next_shot(shot) if shot else None
        if v is None or nxt is None or not v.usable:
            return False
        out = self._frames_dir() / f"{nxt.id}-start-from-{v.id}.png"
        try:
            save_frame(Path(v.path), self.frame_at.value(), out)
        except ValueError as exc:
            QMessageBox.warning(self, "Generate", str(exc))
            return False
        self._replace_shot(nxt.model_copy(update={"start_frame": str(out)}))
        self.version_detail.setText(
            f"Saved the frame at {self.frame_at.value():.2f} s as the start "
            f"frame of {nxt.id}.")
        self._on_changed()
        return True
