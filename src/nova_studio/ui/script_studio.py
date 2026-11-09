"""Script mode (roadmap M2): write or open a script, break it down, direct it.

Left: the script editor. Right: every dialogue line with its direction
(emotion, intensity, pace), where it came from (script / suggested / you)
and whether it is approved. The local model only suggests; the user approves
lines one by one (or picks values, which approves them), then approves the
plan as a whole.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..core.model_resolver import ModelResolver
from ..core.setup_check import module_available
from ..director.breakdown import BreakdownError, apply_breakdown
from ..director.direction import (EMOTIONS, INTENSITIES, PACES, approve_line,
                                  approve_plan, llama_complete, set_direction,
                                  suggest_directions, unapprove_plan)
from ..director.model import DirectionSource
from ..director.parser import parse_script

_COLS = ["#", "Scene", "Speaker", "Line", "Script direction",
         "Emotion", "Intensity", "Pace", "Source", "Approved"]
_EMO, _INT, _PACE, _SRC, _APP = 5, 6, 7, 8, 9
LINE_COLUMN_WIDTH = 280
_SOURCE_LABEL = {DirectionSource.SCRIPT: "script", DirectionSource.SUGGESTED: "suggested",
                 DirectionSource.USER: "you", None: "-"}


def script_model_status(models_dir: Path) -> tuple[Optional[str], str]:
    """(model path, '') when local suggestions can run, else (None, reason)."""
    if not module_available("llama_cpp"):
        return None, ("The local AI runtime (llama.cpp) is not installed in this "
                      "NOVA build, so suggestions are unavailable.")
    models = ModelResolver(models_dir).list_script_models()
    if not models:
        return None, (f"No script model installed. Put a Qwen2.5 GGUF file in "
                      f"{Path(models_dir) / 'script'}.")
    preferred = sorted(models, key=lambda p: (0 if "1.5b" in p.name.lower() else 1, p.name))
    return str(preferred[0]), ""


class _SuggestWorker(QObject):
    finished = Signal(object, str)   # (SuggestionReport | None, error)

    def __init__(self, project, model_path: str) -> None:
        super().__init__()
        self.project, self.model_path = project, model_path
        self.cancelled = False

    def run(self) -> None:
        try:
            rep = suggest_directions(self.project, llama_complete(self.model_path),
                                     cancel=lambda: self.cancelled)
            self.finished.emit(rep, "")
        except Exception as exc:  # model load/run failure: report, change nothing else
            self.finished.emit(None, f"{type(exc).__name__}: {exc}")


class _ExportWorker(QObject):
    finished = Signal(object, str)   # (AnimaticReport | None, error)

    def __init__(self, export: Callable[[], object]) -> None:
        super().__init__()
        self.export = export

    def run(self) -> None:
        try:
            self.finished.emit(self.export(), "")
        except Exception as exc:
            self.finished.emit(None, f"{type(exc).__name__}: {exc}")


class ScriptStudioPanel(QWidget):
    def __init__(self, project, models_dir: Path,
                 on_changed: Callable[[], None] = lambda: None,
                 export_dir: Optional[Path] = None,
                 audio_dir: Optional[Path] = None,
                 renderer_factory: Optional[Callable[[], object]] = None) -> None:
        super().__init__()
        self.project = project
        self.models_dir = Path(models_dir)
        self.on_changed = on_changed
        # Animatic export: where the MP4 goes, where voiced takes live, and
        # how to get a renderer. Export is offered only when all three exist.
        self.export_dir = Path(export_dir) if export_dir else None
        self.audio_dir = Path(audio_dir) if audio_dir else None
        self.renderer_factory = renderer_factory
        self._thread: Optional[QThread] = None
        self._worker: Optional[_SuggestWorker] = None
        self._export_thread: Optional[QThread] = None
        self._export_worker: Optional[_ExportWorker] = None
        self.last_animatic = None
        self._filling = False

        split = QSplitter(Qt.Horizontal)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.addWidget(QLabel("<b>Script</b> (Fountain screenplay or 'Name: line')"))
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText(
            "INT. KITCHEN - NIGHT\n\nAva waits by the window.\n\nAVA\nYou came back!\n\n"
            "BEN\n(quietly)\nI promised I would.")
        self.editor.setPlainText(project.director.script_text)
        lv.addWidget(self.editor, 1)
        row = QHBoxLayout()
        self.open_btn = QPushButton("Open script file…")
        self.open_btn.clicked.connect(self._open_file)
        self.breakdown_btn = QPushButton("Break down script")
        self.breakdown_btn.clicked.connect(self.break_down)
        row.addWidget(self.open_btn)
        row.addStretch(1)
        row.addWidget(self.breakdown_btn)
        lv.addLayout(row)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        lv.addWidget(self.summary)
        split.addWidget(left)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.addWidget(QLabel("<b>Direction</b> - suggestions are used only after you approve them"))
        self.table = QTableWidget(0, len(_COLS))
        self.table.setHorizontalHeaderLabels(_COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setWordWrap(True)
        rv.addWidget(self.table, 1)
        btns = QHBoxLayout()
        self.suggest_btn = QPushButton("Suggest direction (local AI)")
        self.suggest_btn.clicked.connect(self.suggest)
        self.cancel_btn = QPushButton("Stop")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel)
        self.approve_btn = QPushButton("Approve selected lines")
        self.approve_btn.clicked.connect(self.approve_selected)
        self.plan_btn = QPushButton()
        self.plan_btn.clicked.connect(self.toggle_plan)
        self.animatic_btn = QPushButton("Export animatic")
        self.animatic_btn.setToolTip(
            "A watchable cut of the plan: approved designs or title cards, the "
            "recorded lines where they exist, subtitles for the rest.")
        self.animatic_btn.clicked.connect(self.export_animatic)
        for b in (self.suggest_btn, self.cancel_btn, self.approve_btn):
            btns.addWidget(b)
        btns.addStretch(1)
        self.moves_check = QCheckBox("2.5D camera moves")
        self.moves_check.setChecked(True)
        self.moves_check.setToolTip(
            "Give still frames a gentle push-in or sideways move with parallax, "
            "rendered on this PC. Uses a depth model if one is installed, otherwise "
            "an approximate depth (and the report says which).")
        btns.addWidget(self.moves_check)
        btns.addWidget(self.animatic_btn)
        btns.addWidget(self.plan_btn)
        rv.addLayout(btns)
        self.status = QLabel()
        self.status.setWordWrap(True)
        rv.addWidget(self.status)
        split.addWidget(right)
        split.setSizes([360, 900])

        lay = QVBoxLayout(self)
        lay.addWidget(split)
        self.refresh()

    # ---- state ----------------------------------------------------------------
    def refresh(self) -> None:
        self._fill_table()
        d = self.project.director
        approved = sum(1 for x in d.lines if x.approved)
        locked = d.plan_approved
        self.plan_btn.setText("Unapprove plan" if locked else "Approve plan")
        self.plan_btn.setEnabled(bool(d.lines))
        self.breakdown_btn.setEnabled(not locked)
        self.editor.setReadOnly(locked)
        model, reason = script_model_status(self.models_dir)
        running = self._thread is not None
        self.suggest_btn.setEnabled(bool(model) and bool(d.lines) and not locked and not running)
        self.suggest_btn.setToolTip(reason or f"Uses {Path(model).name} on this PC; nothing is sent online.")
        self.approve_btn.setEnabled(bool(d.lines) and not locked)
        can_export = bool(self.project.shots) and self.export_dir is not None \
            and self.renderer_factory is not None
        self.animatic_btn.setEnabled(can_export and self._export_thread is None)
        if not d.lines and not d.breakdown_at:
            self.status.setText("Write or open a script, then break it down.")
        else:
            state = "approved" if locked else "not approved"
            self.status.setText(
                f"{approved} of {len(d.lines)} lines approved. Plan {state}."
                + ("" if model else f"\n{reason}"))

    def _fill_table(self) -> None:
        self._filling = True
        p, d = self.project, self.project.director
        names = {c.id: c.name for c in p.characters}
        scenes = {s.index: s for s in d.scenes}
        rows = [(dl, d.line(dl.id)) for dl in p.dialogue if d.line(dl.id)]
        self.table.setRowCount(len(rows))
        for r, (dl, dd) in enumerate(rows):
            sc = scenes.get(dd.scene_index)
            cells = [str(dl.order + 1), (sc.location or sc.heading) if sc else "",
                     names.get(dl.speaker_id, "?"), dl.text,
                     " ".join(x for x in (dd.extension and f"({dd.extension})", dd.parenthetical) if x),
                     None, None, None, _SOURCE_LABEL[dd.source], "yes" if dd.approved else "no"]
            for c, val in enumerate(cells):
                if val is not None:
                    item = QTableWidgetItem(val)
                    if c == 0:
                        item.setData(Qt.UserRole, dl.id)
                    if c == 4 and dd.note:
                        item.setToolTip(dd.note)
                    self.table.setItem(r, c, item)
            for c, allowed, val in ((_EMO, EMOTIONS, dd.emotion), (_INT, INTENSITIES, dd.intensity),
                                    (_PACE, PACES, dd.pace)):
                combo = QComboBox()
                combo.addItem("-")
                combo.addItems(list(allowed))
                combo.setCurrentText(val or "-")
                combo.setEnabled(not d.plan_approved)
                combo.currentTextChanged.connect(lambda _t, row=r: self._user_changed(row))
                self.table.setCellWidget(r, c, combo)
        self.table.resizeColumnsToContents()
        # The dialogue itself must stay readable: give it a fixed, wide column
        # and wrap long lines, rather than letting the combo columns squeeze it.
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Interactive)
        self.table.setColumnWidth(3, LINE_COLUMN_WIDTH)
        self.table.resizeRowsToContents()
        self._filling = False

    def _line_id(self, row: int) -> str:
        return self.table.item(row, 0).data(Qt.UserRole)

    def _combo_value(self, row: int, col: int) -> Optional[str]:
        v = self.table.cellWidget(row, col).currentText()
        return None if v == "-" else v

    # ---- actions ------------------------------------------------------------------
    def _open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open script", "", "Scripts (*.fountain *.spmd *.txt);;All files (*)")
        if path:
            self.editor.setPlainText(Path(path).read_text(encoding="utf-8", errors="replace"))

    def break_down(self, confirm: Optional[Callable[[str], bool]] = None) -> bool:
        text = self.editor.toPlainText()
        parsed = parse_script(text)
        ask = confirm or (lambda msg: QMessageBox.question(
            self, "Replace existing work?", msg) == QMessageBox.Yes)
        try:
            summary = apply_breakdown(self.project, parsed, text)
        except BreakdownError as exc:
            if "not made from the script" not in str(exc) or not ask(str(exc)):
                self.summary.setText(f"<span style='color:#c62828'>{exc}</span>")
                return False
            summary = apply_breakdown(self.project, parsed, text, replace_existing=True)
        mins, secs = divmod(int(round(summary.running_time_s)), 60)
        parts = [f"{summary.scenes} scene(s), {summary.lines} line(s), {summary.shots} shot(s), "
                 f"about {mins}m {secs:02d}s."]
        if summary.new_characters:
            parts.append("New characters (unapproved): " + ", ".join(summary.new_characters) + ".")
        if summary.reused_characters:
            parts.append("Existing characters reused: " + ", ".join(summary.reused_characters) + ".")
        parts += summary.warnings
        self.summary.setText("\n".join(parts))
        self.refresh()
        self.on_changed()
        return True

    def suggest(self) -> None:
        model, reason = script_model_status(self.models_dir)
        if not model:
            self.status.setText(reason)
            return
        self._thread = QThread(self)
        self._worker = _SuggestWorker(self.project, model)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._suggested)
        self.suggest_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.status.setText("Asking the local script model… (runs on this PC)")
        self._thread.start()

    def _cancel(self) -> None:
        if self._worker:
            self._worker.cancelled = True
            self.status.setText("Stopping after the current batch…")

    def _suggested(self, rep, error: str) -> None:
        self._thread.quit()
        self._thread.wait()
        self._thread = self._worker = None
        self.cancel_btn.setEnabled(False)
        self.refresh()
        if error:
            self.status.setText(f"Suggestions failed: {error}")
        else:
            msg = f"{rep.suggested} line(s) suggested; {rep.kept_script} kept the script's direction."
            if rep.rejected:
                msg += f" {len(rep.rejected)} answer(s) were invalid and ignored."
            self.status.setText(msg + " Review them, then approve.")
        self.on_changed()

    def _user_changed(self, row: int) -> None:
        if self._filling:
            return
        set_direction(self.project, self._line_id(row), self._combo_value(row, _EMO),
                      self._combo_value(row, _INT), self._combo_value(row, _PACE))
        self.refresh()
        self.on_changed()

    def approve_selected(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        for r in rows:
            approve_line(self.project, self._line_id(r))
        self.refresh()
        self.on_changed()

    def toggle_plan(self) -> None:
        if self.project.director.plan_approved:
            unapprove_plan(self.project)
        else:
            try:
                approve_plan(self.project)
            except ValueError as exc:
                self.status.setText(str(exc))
                return
        self.refresh()
        self.on_changed()


    # ---- animatic ----------------------------------------------------------------
    def export_animatic(self) -> None:
        from ..director.animatic import build_animatic
        from ..media.parallax import depth_source
        from ..storage.asset_registry import safe_filename

        out = self.export_dir / f"{safe_filename(self.project.name, 'film')}_animatic.mp4"
        renderer = self.renderer_factory()
        self._export_thread = QThread(self)
        moves = self.moves_check.isChecked()
        depth = depth_source(self.models_dir) if moves else None
        self._export_worker = _ExportWorker(lambda: build_animatic(
            self.project, renderer, self.audio_dir, out,
            camera_moves=moves, depth=depth))
        self._export_worker.moveToThread(self._export_thread)
        self._export_thread.started.connect(self._export_worker.run)
        self._export_worker.finished.connect(self._exported)
        self.animatic_btn.setEnabled(False)
        self.status.setText("Exporting the animatic… (rendered on this PC)")
        self._export_thread.start()

    def _exported(self, rep, error: str) -> None:
        self._export_thread.quit()
        self._export_thread.wait()
        self._export_thread = self._export_worker = None
        self.last_animatic = rep
        self.refresh()
        if error:
            self.status.setText(f"Animatic export failed: {error}")
        else:
            text = rep.summary()
            if rep.ok:
                text += f"\nSaved to {rep.output_path}"
            self.status.setText(text)


def mount_script(window) -> ScriptStudioPanel:
    paths = window.studio.config.paths
    project_dir = paths.projects / window.project.id
    from PySide6.QtWidgets import QTabWidget
    from .locations_panel import LocationsPanel

    def changed() -> None:
        locations.refresh()          # a breakdown may have added locations
        window._poll_project()

    panel = ScriptStudioPanel(
        window.project, paths.models, on_changed=changed,
        export_dir=project_dir,
        # Same takes folder the Characters mode voices lines into.
        audio_dir=project_dir / "dialogue",
        renderer_factory=lambda: window.studio.renderer)
    locations = LocationsPanel(window.project, export_dir=project_dir,
                               on_changed=window._poll_project)
    tabs = QTabWidget()
    tabs.addTab(panel, "Script && direction")
    tabs.addTab(locations, "Locations")
    tabs.currentChanged.connect(lambda _i: locations.refresh())
    window.set_tab_widget("script", tabs)
    window.locations = locations
    return panel
