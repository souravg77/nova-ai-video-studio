"""PySide6 main window (roadmap section 5 Desktop UI + section 7 milestones).

Project workflow, profile selector, hardware report, job status and — most
importantly — honest failure notices. The window talks only to the Studio
facade; it never guesses capability in the UI layer.

Rendering runs on the Studio's worker thread; the UI subscribes via a job
listener marshalled back onto the Qt thread with a signal.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QListWidget, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QTextEdit, QVBoxLayout, QWidget,
    QGroupBox, QSpinBox, QLineEdit, QSplitter, QPlainTextEdit,
    QDoubleSpinBox, QCheckBox, QInputDialog,
)

from ..core.capability import Profile
from ..core.studio import Studio
from ..models.job import GenerationState, Job, JobKind, JobState
from ..models.project import Scene
from .voice_panel import VoiceStudioPanel


class JobBridge(QObject):
    """Marshals worker-thread job updates onto the Qt main thread."""
    updated = Signal(object)


class MainWindow(QMainWindow):
    def __init__(self, studio: Studio) -> None:
        super().__init__()
        self.studio = studio
        self.project = studio.new_project("Untitled Project")
        self.bridge = JobBridge()
        self.bridge.updated.connect(self._on_job_update)
        # The job currently running from this window (render or auto-video), so
        # Cancel knows what to stop.
        self.active_job_id: str | None = None
        # Voice Studio state: (engine_id, voice_path, capabilities) per combo
        # row, and a pronunciation dictionary the user edits.
        self._voice_entries: list[tuple] = []
        from ..voice.expression import PronunciationDict
        self._pron = PronunciationDict()
        # Approved identity photos for the P4.6 still-video export.
        self._approved_photos: list[str] = []
        self.setWindowTitle("NOVA AI Video Studio")
        self.resize(1100, 720)
        self._build()
        self._refresh_hardware()

    # ------------------------------------------------------------------
    def _build(self) -> None:
        splitter = QSplitter(Qt.Horizontal)

        # ---- Left: project + assets + scenes ----
        left = QWidget()
        lv = QVBoxLayout(left)

        proj_box = QGroupBox("Project")
        pv = QVBoxLayout(proj_box)
        self.name_edit = QLineEdit(self.project.name)
        self.name_edit.editingFinished.connect(self._rename_project)
        pv.addWidget(QLabel("Name:"))
        pv.addWidget(self.name_edit)
        res_row = QHBoxLayout()
        self.w_spin = QSpinBox(); self.w_spin.setRange(240, 7680); self.w_spin.setValue(1920)
        self.h_spin = QSpinBox(); self.h_spin.setRange(240, 4320); self.h_spin.setValue(1080)
        self.fps_spin = QSpinBox(); self.fps_spin.setRange(12, 60); self.fps_spin.setValue(30)
        res_row.addWidget(QLabel("W")); res_row.addWidget(self.w_spin)
        res_row.addWidget(QLabel("H")); res_row.addWidget(self.h_spin)
        res_row.addWidget(QLabel("fps")); res_row.addWidget(self.fps_spin)
        pv.addLayout(res_row)
        lv.addWidget(proj_box)

        assets_box = QGroupBox("Assets")
        av = QVBoxLayout(assets_box)
        self.asset_list = QListWidget()
        av.addWidget(self.asset_list)
        btn_row = QHBoxLayout()
        import_btn = QPushButton("Import media…")
        import_btn.clicked.connect(self._import_media)
        add_scene_btn = QPushButton("Add as scene")
        add_scene_btn.clicked.connect(self._add_scene_from_selected)
        btn_row.addWidget(import_btn); btn_row.addWidget(add_scene_btn)
        av.addLayout(btn_row)
        lv.addWidget(assets_box)

        scenes_box = QGroupBox("Scenes (timeline)")
        sv = QVBoxLayout(scenes_box)
        self.scene_list = QListWidget()
        sv.addWidget(self.scene_list)
        lv.addWidget(scenes_box)

        splitter.addWidget(left)

        # ---- Right: hardware, profile, render, jobs ----
        right = QWidget()
        rv = QVBoxLayout(right)

        hw_box = QGroupBox("Hardware & capability")
        hv = QVBoxLayout(hw_box)
        self.hw_label = QLabel("Scanning…")
        self.hw_label.setWordWrap(True)
        hv.addWidget(self.hw_label)
        hw_btn_row = QHBoxLayout()
        rescan_btn = QPushButton("Rescan hardware")
        rescan_btn.clicked.connect(self._rescan)
        bench_btn = QPushButton("Run benchmarks")
        bench_btn.clicked.connect(self._run_benchmarks)
        hw_btn_row.addWidget(rescan_btn); hw_btn_row.addWidget(bench_btn)
        hv.addLayout(hw_btn_row)
        rv.addWidget(hw_box)

        prof_box = QGroupBox("Performance profile")
        prv = QVBoxLayout(prof_box)
        self.profile_combo = QComboBox()
        self.profile_combo.addItems(["Auto", "Balanced", "High", "Maximum"])
        self.profile_combo.currentTextChanged.connect(self._profile_changed)
        prv.addWidget(self.profile_combo)
        self.profile_reason = QLabel("")
        self.profile_reason.setWordWrap(True)
        prv.addWidget(self.profile_reason)
        rv.addWidget(prof_box)

        # ---- Auto Video (P2 pipeline: script -> narration -> render) ----
        auto_box = QGroupBox("Auto Video (AI: script → narration → render)")
        auv = QVBoxLayout(auto_box)
        auv.addWidget(QLabel("Topic / brief:"))
        self.brief_edit = QPlainTextEdit()
        self.brief_edit.setPlaceholderText(
            "e.g. A 30-second teaser about our new cold-brew coffee")
        self.brief_edit.setFixedHeight(60)
        auv.addWidget(self.brief_edit)
        self.readiness_label = QLabel("")
        self.readiness_label.setWordWrap(True)
        auv.addWidget(self.readiness_label)
        auto_btn_row = QHBoxLayout()
        self.auto_btn = QPushButton("Auto Video")
        self.auto_btn.clicked.connect(self._auto_video)
        self.refresh_ready_btn = QPushButton("Check models")
        self.refresh_ready_btn.clicked.connect(self._refresh_readiness)
        auto_btn_row.addWidget(self.auto_btn)
        auto_btn_row.addWidget(self.refresh_ready_btn)
        auv.addLayout(auto_btn_row)
        rv.addWidget(auto_box)

        # ---- Voice Studio (Phase 3) ----
        voice_box = QGroupBox("Voice Studio")
        vo = QVBoxLayout(voice_box)
        self.voice_status = QLabel("")
        self.voice_status.setWordWrap(True)
        vo.addWidget(self.voice_status)
        pick_row = QHBoxLayout()
        pick_row.addWidget(QLabel("Voice:"))
        self.voice_combo = QComboBox()
        self.voice_combo.currentIndexChanged.connect(self._voice_selected)
        pick_row.addWidget(self.voice_combo)
        vo.addLayout(pick_row)
        # Expression controls (disabled when the selected engine can't do them).
        ctl_row = QHBoxLayout()
        ctl_row.addWidget(QLabel("Speed"))
        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(0.5, 2.0); self.speed_spin.setSingleStep(0.05)
        self.speed_spin.setValue(1.0)
        ctl_row.addWidget(self.speed_spin)
        ctl_row.addWidget(QLabel("Pause ms"))
        self.pause_spin = QSpinBox()
        self.pause_spin.setRange(0, 1000); self.pause_spin.setSingleStep(50)
        ctl_row.addWidget(self.pause_spin)
        vo.addLayout(ctl_row)
        self.unsupported_label = QLabel("")
        self.unsupported_label.setWordWrap(True)
        vo.addWidget(self.unsupported_label)
        v_btn_row = QHBoxLayout()
        self.audition_btn = QPushButton("Audition")
        self.audition_btn.clicked.connect(self._audition)
        self.pron_btn = QPushButton("Pronunciations…")
        self.pron_btn.clicked.connect(self._edit_pronunciation)
        self.regen_btn = QPushButton("Regenerate scene narration")
        self.regen_btn.clicked.connect(self._regen_scene)
        v_btn_row.addWidget(self.audition_btn)
        v_btn_row.addWidget(self.pron_btn)
        vo.addLayout(v_btn_row)
        vo.addWidget(self.regen_btn)
        self.refresh_voices_btn = QPushButton("Refresh voices")
        self.refresh_voices_btn.clicked.connect(self._refresh_voices)
        vo.addWidget(self.refresh_voices_btn)
        rv.addWidget(voice_box)

        # ---- Identity & Motion Studio (Phase 4) ----
        p4_box = QGroupBox("Identity & Motion Studio (talking head)")
        p4 = QVBoxLayout(p4_box)
        self.p4_status = QLabel("")
        self.p4_status.setWordWrap(True)
        p4.addWidget(self.p4_status)
        p4_btn_row = QHBoxLayout()
        self.p4_import_btn = QPushButton("Import 3 photos…")
        self.p4_import_btn.clicked.connect(self._import_photos)
        self.p4_check_btn = QPushButton("Check generation")
        self.p4_check_btn.clicked.connect(self._check_generation)
        p4_btn_row.addWidget(self.p4_import_btn)
        p4_btn_row.addWidget(self.p4_check_btn)
        p4.addLayout(p4_btn_row)
        # P4.6: usable still-video export on this hardware.
        self.photo_video_btn = QPushButton("Make photo video (no GPU needed)")
        self.photo_video_btn.clicked.connect(self._make_photo_video)
        self.photo_video_btn.setEnabled(False)
        p4.addWidget(self.photo_video_btn)
        rv.addWidget(p4_box)

        render_box = QGroupBox("Render (from scenes, no AI)")
        rvv = QVBoxLayout(render_box)
        self.render_btn = QPushButton("Render video")
        self.render_btn.clicked.connect(self._render)
        rvv.addWidget(self.render_btn)
        self.progress = QProgressBar(); self.progress.setRange(0, 100)
        rvv.addWidget(self.progress)
        self.stage_label = QLabel("")
        self.stage_label.setWordWrap(True)
        rvv.addWidget(self.stage_label)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._cancel_job)
        self.cancel_btn.setEnabled(False)
        rvv.addWidget(self.cancel_btn)
        rv.addWidget(render_box)

        jobs_box = QGroupBox("Job status & notices")
        jv = QVBoxLayout(jobs_box)
        self.job_log = QTextEdit(); self.job_log.setReadOnly(True)
        jv.addWidget(self.job_log)
        rv.addWidget(jobs_box)

        splitter.addWidget(right)

        # ---- Voice Studio (Phase 3) as a third pane ----
        self.voice_panel = VoiceStudioPanel(self.studio)
        splitter.addWidget(self.voice_panel)

        splitter.setSizes([400, 500, 360])
        self.setCentralWidget(splitter)

        self._profile_changed("Auto")
        self._refresh_readiness()
        self._refresh_voices()
        self._check_generation()

    # ------------------------------------------------------------------
    def _rename_project(self) -> None:
        self.project.name = self.name_edit.text().strip() or "Untitled Project"
        self.studio.save_project(self.project)

    def _refresh_hardware(self) -> None:
        r = self.studio.report
        text = r.human_summary()
        if r.warnings:
            text += "\n\nNotices:\n" + "\n".join(f"• {w}" for w in r.warnings)
        self.hw_label.setText(text)
        self._profile_changed(self.profile_combo.currentText())

    def _rescan(self) -> None:
        self.studio.rescan_hardware()
        self._refresh_hardware()
        self._log("Hardware rescanned.")

    def _run_benchmarks(self) -> None:
        self._log("Running benchmarks (this may take a moment)…")
        results = self.studio.run_benchmarks(runs=3)
        for b in results:
            self._log(f"  {b.capability} [{b.backend_path}]: {b.outcome.value}"
                      + (f" median={b.median_runtime_s}s" if b.median_runtime_s else "")
                      + f" — {b.evidence}")
        self._profile_changed(self.profile_combo.currentText())

    def _profile_changed(self, text: str) -> None:
        mapping = {"Auto": Profile.AUTO, "Balanced": Profile.BALANCED,
                   "High": Profile.HIGH, "Maximum": Profile.MAXIMUM}
        eff, reason = self.studio.effective_profile(mapping.get(text, Profile.AUTO))
        self.profile_reason.setText(f"Effective: {eff.value}\n{reason}")

    def _import_media(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Import media")
        for path in paths:
            try:
                asset = self.studio.import_media(self.project, path)
                self.asset_list.addItem(
                    f"[{asset.kind.value}] {Path(asset.path).name}"
                    + (f"  {asset.width}x{asset.height}" if asset.width else "")
                    + (f"  {asset.duration_s:.1f}s" if asset.duration_s else ""))
                self.asset_list.item(self.asset_list.count() - 1).setData(
                    Qt.UserRole, asset.id)
            except ValueError as exc:
                QMessageBox.warning(self, "Import rejected", str(exc))

    def _add_scene_from_selected(self) -> None:
        item = self.asset_list.currentItem()
        if not item:
            QMessageBox.information(self, "No asset", "Select an asset first.")
            return
        asset_id = item.data(Qt.UserRole)
        asset = self.project.asset_by_id(asset_id)
        if asset is None:
            return
        from ..models.project import AssetKind
        motion = "kenburns" if asset.kind == AssetKind.IMAGE else None
        scene = Scene(title=f"Scene {len(self.project.scenes)+1}",
                      caption="", visual_asset_id=asset_id,
                      duration_s=asset.duration_s or 5.0, motion_effect=motion)
        self.project.add_scene(scene)
        self.studio.save_project(self.project)
        self.scene_list.addItem(f"{scene.title}: {Path(asset.path).name}")
        # Keep the Voice Studio's per-scene selector in sync.
        self.voice_panel.set_scenes([s.title for s in self.project.scenes])

    # ---- Auto Video (P2) ---------------------------------------------
    @staticmethod
    def _readiness_text(readiness: dict) -> str:
        """Format per-stage readiness honestly (shared with tests)."""
        def mark(ok: bool) -> str:
            return "✓" if ok else "✗"
        lines = []
        s = readiness["script"]
        lines.append(f"{mark(s['ready'])} Qwen2.5 script: "
                     + (s.get("model") or "not installed"))
        t = readiness["tts"]
        lines.append(f"{mark(t['ready'])} Piper narration: "
                     + (t.get("voice") or "not installed"))
        lines.append(f"{mark(readiness['render']['ready'])} FFmpeg render: ready")
        if not s["ready"]:
            lines.append(f"   → {s['blocker']}")
        if not t["ready"]:
            lines.append(f"   → {t['blocker']}")
        return "\n".join(lines)

    def _refresh_readiness(self) -> None:
        self.studio.refresh_pipeline()
        readiness = self.studio.pipeline_readiness()
        self.readiness_label.setText(self._readiness_text(readiness))
        # Auto Video is enabled only when script + tts are both ready.
        ready = readiness["script"]["ready"] and readiness["tts"]["ready"]
        self.auto_btn.setEnabled(ready)
        self.auto_btn.setToolTip(
            "" if ready else "Install a Qwen2.5 GGUF in models/script and a "
            "Piper voice in models/tts, then click 'Check models'.")

    def _auto_video(self) -> None:
        brief = self.brief_edit.toPlainText().strip()
        if not brief:
            QMessageBox.information(self, "Need a topic",
                                    "Enter a topic/brief first.")
            return
        self.project.target_width = self.w_spin.value()
        self.project.target_height = self.h_spin.value()
        self.project.target_fps = self.fps_spin.value()
        self.studio.save_project(self.project)
        self._set_running(True)
        self.progress.setValue(0)
        self.stage_label.setText("Starting Auto Video pipeline…")
        self._log(f"Auto Video: '{brief}'")
        try:
            eff, _ = self.studio.effective_profile(Profile.AUTO)
            preset = "veryfast" if eff == Profile.BALANCED else "medium"
            job = self.studio.auto_video(
                self.project, brief=brief,
                listener=lambda j: self.bridge.updated.emit(j), preset=preset)
            self.active_job_id = job.id
        except RuntimeError as exc:
            self._set_running(False)
            QMessageBox.warning(self, "Cannot start Auto Video", str(exc))
            self._log(f"Auto Video blocked: {exc}")

    def _cancel_job(self) -> None:
        if self.active_job_id:
            if self.studio.cancel_job(self.active_job_id):
                self._log("Cancellation requested…")
                self.stage_label.setText("Cancelling…")

    def _set_running(self, running: bool) -> None:
        self.render_btn.setEnabled(not running)
        self.cancel_btn.setEnabled(running)
        if running:
            self.auto_btn.setEnabled(False)
        else:
            # Re-evaluate Auto Video availability (also re-enables auto_btn
            # only if models are still ready).
            self._refresh_readiness()

    # ---- Voice Studio (Phase 3) --------------------------------------
    @staticmethod
    def _voice_status_text(gallery) -> str:
        lines = []
        for e in gallery.engines:
            mark = "✓" if e.available else "✗"
            nv = len(e.voices)
            lines.append(f"{mark} {e.display_name}: "
                         + (f"{nv} voice(s)" if e.available
                            else (e.reason or "unavailable")))
        return "\n".join(lines)

    def _refresh_voices(self) -> None:
        gallery = self.studio.voice_gallery()
        self.voice_status.setText(self._voice_status_text(gallery))
        self._voice_entries = []
        self.voice_combo.clear()
        for e in gallery.engines:
            if not e.available:
                continue
            for v in e.voices:
                self._voice_entries.append((e.engine_id, v.path, e.capabilities))
                self.voice_combo.addItem(f"{e.display_name}: {v.name} "
                                         f"[{v.language}]")
        any_voice = bool(self._voice_entries)
        for b in (self.audition_btn, self.regen_btn):
            b.setEnabled(any_voice)
        if not any_voice:
            self.unsupported_label.setText(
                "No usable voice installed. Add a Piper voice (.onnx + "
                ".onnx.json) to models/tts and click Refresh voices.")
        self._voice_selected(self.voice_combo.currentIndex())

    def _current_voice(self):
        i = self.voice_combo.currentIndex()
        if 0 <= i < len(self._voice_entries):
            return self._voice_entries[i]
        return None

    def _voice_selected(self, index: int) -> None:
        entry = self._current_voice()
        if not entry:
            return
        _engine_id, _voice_path, caps = entry
        # Disable controls the engine can't do; label what's unsupported.
        self.speed_spin.setEnabled(bool(caps.speed))
        self.pause_spin.setEnabled(bool(caps.pause))
        self.pron_btn.setEnabled(bool(caps.pronunciation))
        unsupported = [name for name, ok in (
            ("speed", caps.speed), ("pause", caps.pause),
            ("emphasis", caps.emphasis), ("emotion", caps.emotion),
            ("pronunciation", caps.pronunciation)) if not ok]
        self.unsupported_label.setText(
            "Unsupported by this voice: " + ", ".join(unsupported)
            if unsupported else "All basic settings supported by this voice.")

    def _expression(self):
        from ..voice.expression import ExpressionSettings
        return ExpressionSettings(
            speed=float(self.speed_spin.value()),
            pause_sentence_ms=int(self.pause_spin.value()))

    def _audition(self) -> None:
        entry = self._current_voice()
        if not entry:
            QMessageBox.information(self, "No voice", "Select a voice first.")
            return
        engine_id, voice_path, _caps = entry
        self._log("Auditioning voice…")
        res = self.studio.audition_voice(
            engine_id, voice_path, expression=self._expression(),
            pronunciation=self._pron)
        if res["ok"]:
            self._log(f"✓ Audition sample: {res['path']}")
            if res.get("unsupported"):
                self._log("  (ignored unsupported: "
                          + ", ".join(res["unsupported"]) + ")")
            QMessageBox.information(
                self, "Audition ready",
                f"Preview saved:\n{res['path']}\n\nOpen it to listen.")
        else:
            self._log(f"✗ Audition failed: {res['message']}")
            QMessageBox.warning(self, "Audition failed", res["message"])

    def _edit_pronunciation(self) -> None:
        # Minimal editor: add one word->say-as entry at a time.
        word, ok = QInputDialog.getText(self, "Pronunciation",
                                        "Word (e.g. NOVA):")
        if not ok or not word.strip():
            return
        say_as, ok = QInputDialog.getText(
            self, "Pronunciation", f"Say '{word}' as:")
        if not ok or not say_as.strip():
            return
        self._pron.add(word.strip(), say_as.strip())
        self._log(f"Pronunciation: '{word}' → '{say_as}' "
                  f"({len(self._pron.entries)} total)")

    def _regen_scene(self) -> None:
        entry = self._current_voice()
        if not entry:
            QMessageBox.information(self, "No voice", "Select a voice first.")
            return
        if not self.project.scenes:
            QMessageBox.information(self, "No scenes",
                                    "Add scenes before regenerating narration.")
            return
        idx, ok = QInputDialog.getInt(
            self, "Regenerate scene",
            f"Scene number (1–{len(self.project.scenes)}):",
            1, 1, len(self.project.scenes))
        if not ok:
            return
        engine_id, voice_path, _caps = entry
        profile = self.studio.build_voice_profile(
            engine_id, voice_path, expression=self._expression(),
            pronunciation=self._pron)
        self._log(f"Regenerating narration for scene {idx}…")
        try:
            mgr, scenes = self.studio.narrate_project(self.project, profile)
            scenes = self.studio.regenerate_scene_narration(
                mgr, scenes, idx - 1,
                str(self.studio.config.paths.projects / self.project.id
                    / "narration"))
            sn = scenes[idx - 1]
            if sn.ok:
                self._log(f"✓ Scene {idx} narration regenerated: {sn.audio_path}")
            else:
                self._log(f"✗ Scene {idx} failed: {sn.message}")
                QMessageBox.warning(self, "Regeneration failed", sn.message)
        except Exception as exc:
            self._log(f"✗ Regeneration error: {exc}")
            QMessageBox.warning(self, "Regeneration failed", str(exc))

    # ---- Identity & Motion Studio (Phase 4) --------------------------
    @staticmethod
    def _generation_status_text(decision) -> str:
        """Honest one-liner for talking-head generation availability."""
        if decision.can_attempt:
            return "✓ Talking-head generation: supported on this PC."
        return (f"✗ Talking-head generation: {decision.verdict.value}\n"
                f"   {decision.blocker}\n"
                f"   Fallback: {decision.suggested_fallback}")

    def _check_generation(self) -> None:
        # Assume the candidate engine's weights may be present; the gate still
        # blocks on hardware. We report for the default engine.
        reg = self.studio.generation_registry(installed_ids={"sadtalker"})
        decision = reg.decide("sadtalker")
        self.p4_status.setText(self._generation_status_text(decision))

    def _import_photos(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Import exactly 3 identity photos")
        if not paths:
            return
        if len(paths) != 3:
            QMessageBox.information(
                self, "Need three photos",
                f"Please select exactly 3 photos (you selected {len(paths)}).")
            return
        result = self.studio.intake_photos(paths)
        lines = []
        for i, p in enumerate(result.photos, 1):
            if p.usable:
                lines.append(f"Photo {i}: usable ({p.width}x{p.height})")
            else:
                lines.append(f"Photo {i}: UNUSABLE — " + "; ".join(p.reasons))
            for w in p.warnings:
                lines.append(f"   note: {w}")
        self._log("Identity intake:\n" + "\n".join(lines))
        if result.all_usable:
            self._approved_photos = [p.path for p in result.photos]
            self.photo_video_btn.setEnabled(True)
            self._log("✓ All three photos usable. 'Make photo video' is now "
                      "available.")
        else:
            self._approved_photos = []
            self.photo_video_btn.setEnabled(False)
            self._log(f"✗ {len(result.unusable)} photo(s) unusable — fix or "
                      f"replace before proceeding.")
            QMessageBox.warning(
                self, "Some photos unusable",
                "\n".join(l for l in lines if "UNUSABLE" in l))

    def _make_photo_video(self) -> None:
        if len(self._approved_photos) != 3:
            QMessageBox.information(self, "Import photos first",
                                    "Import three usable photos first.")
            return
        # One scene per photo. Narration/caption come from the project's scenes
        # when present, else a simple caption. A selected voice enables
        # narration; otherwise it's a captions-only video.
        entry = self._current_voice()
        voice = None
        if entry:
            engine_id, voice_path, _caps = entry
            voice = {"engine_id": engine_id, "voice_path": voice_path,
                     "expression": {"speed": float(self.speed_spin.value()),
                                    "pause_sentence_ms": int(self.pause_spin.value())}}
        proj_scenes = self.project.scenes
        scenes = []
        for i, photo in enumerate(self._approved_photos):
            caption = ""
            narration = ""
            if i < len(proj_scenes):
                caption = proj_scenes[i].caption or proj_scenes[i].title
                narration = proj_scenes[i].script or ""
            scenes.append({
                "photo_path": photo,
                "caption": caption or f"Photo {i+1}",
                "narration": narration or (caption or f"Photo {i+1}"),
                "duration_s": 4.0, "motion": "kenburns"})
        self.project.target_width = self.w_spin.value()
        self.project.target_height = self.h_spin.value()
        self.project.target_fps = self.fps_spin.value()
        self.studio.save_project(self.project)
        self._set_running(True)
        self.progress.setValue(0)
        self.stage_label.setText("Making photo video…")
        self._log(f"Photo video from {len(scenes)} photos "
                  + ("with narration…" if voice else "(captions only)…"))
        try:
            eff, _ = self.studio.effective_profile(Profile.AUTO)
            preset = "veryfast" if eff == Profile.BALANCED else "medium"
            cfg = {"width": self.project.target_width,
                   "height": self.project.target_height,
                   "fps": self.project.target_fps, "preset": preset,
                   "want_narration": bool(voice), "want_subtitles": True}
            job = self.studio.photo_video(
                self.project, scenes, config=cfg, voice=voice,
                listener=lambda j: self.bridge.updated.emit(j))
            self.active_job_id = job.id
        except RuntimeError as exc:
            self._set_running(False)
            QMessageBox.warning(self, "Cannot make photo video", str(exc))
            self._log(f"Photo video blocked: {exc}")

    # ------------------------------------------------------------------
    def _render(self) -> None:
        self.project.target_width = self.w_spin.value()
        self.project.target_height = self.h_spin.value()
        self.project.target_fps = self.fps_spin.value()
        self.studio.save_project(self.project)
        if not self.project.scenes:
            QMessageBox.information(self, "Nothing to render",
                                    "Add at least one scene first.")
            return
        self._set_running(True)
        self.progress.setValue(0)
        self.stage_label.setText("Rendering…")
        self._log(f"Rendering '{self.project.name}' "
                  f"({self.project.target_width}x{self.project.target_height})…")
        try:
            # Choose a cheaper preset on weak CPUs (Balanced profile).
            eff, _ = self.studio.effective_profile(Profile.AUTO)
            preset = "veryfast" if eff == Profile.BALANCED else "medium"
            job = self.studio.render_project(
                self.project,
                listener=lambda j: self.bridge.updated.emit(j),
                preset=preset)
            self.active_job_id = job.id
        except RuntimeError as exc:
            self._set_running(False)
            QMessageBox.warning(self, "Cannot render", str(exc))
            self._log(f"Render blocked: {exc}")

    # ------------------------------------------------------------------
    def _on_job_update(self, job: Job) -> None:
        self.progress.setValue(int(job.progress * 100))
        if job.logs:
            latest = job.logs[-1].message
            self._log(latest)
            # Surface the current stage (Stage N/3, Render: …) on the label.
            if latest.startswith("Stage ") or latest.startswith("Render"):
                self.stage_label.setText(latest)
        if job.state in (JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED):
            self._set_running(False)
            self.active_job_id = None
            self._announce_final(job)

    def _announce_final(self, job: Job) -> None:
        gs = job.generation_state
        is_auto = job.kind == JobKind.AUTO_VIDEO
        is_photo = job.kind == JobKind.PHOTO_VIDEO
        label = ("Auto Video" if is_auto else
                 "Photo video" if is_photo else "Render")
        if job.state == JobState.COMPLETED and gs == GenerationState.COMPLETED_AND_VALIDATED:
            out = job.outputs[0] if job.outputs else "(unknown)"
            self.stage_label.setText("Completed and validated.")
            self._log(f"✓ Completed and validated: {out}")
            QMessageBox.information(
                self, "Done", f"{label} created and validated:\n{out}")
        elif job.state == JobState.CANCELLED:
            self.stage_label.setText("Cancelled.")
            self._log("Job cancelled.")
        elif job.state == JobState.FAILED:
            # A blocked stage is an honest "can't", not a crash.
            stage = f"{label} stopped: " if (is_auto or is_photo) and job.blocker else ""
            msg = (stage + job.blocker) if job.blocker else (
                f"{label} could not complete." if (is_auto or is_photo)
                else "Render failed.")
            fb = (f"\n\nOptions: {job.suggested_fallback}"
                  if job.suggested_fallback else "")
            self.stage_label.setText(msg)
            self._log(f"✗ {msg}{fb}")
            QMessageBox.warning(self, "Not completed", msg + fb)
        else:
            self._log(f"Job {job.state.value}.")

    def _log(self, msg: str) -> None:
        self.job_log.append(msg)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt signature)
        self.studio.shutdown()
        super().closeEvent(event)
