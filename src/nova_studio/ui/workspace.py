"""NOVA workspace shell (roadmap M1 step 2).

Professional layout around the existing, working editor:

* top toolbar   - project name, last save, hardware profile, active engines,
                  Save and Setup & diagnostics;
* centre        - creative modes as tabs (Script, Characters, Storyboard,
                  Generate, Edit & render). Unbuilt modes are clearly marked
                  placeholders, never fake controls; set_tab_widget() is the
                  single mount point that later panels replace them through;
* left dock     - Library: assets, scenes (and characters on newer projects);
* right dock    - Inspector: read-only properties of the Library selection;
* bottom dock   - Jobs: live queue with state, progress and latest message.

Dock positions/sizes are remembered in settings.json.
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QByteArray, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget, QHBoxLayout, QHeaderView, QLabel, QMainWindow, QMessageBox, QTabWidget,
    QTableWidget, QTableWidgetItem, QToolBar, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from ..core.capability import Profile
from ..core.setup_check import module_available
from ..settings import load_settings, save_settings
from . import workspace_logic as wl
from .main_window import MainWindow


class _JobSignal(QObject):
    """Marshals worker-thread job updates onto the Qt main thread."""
    updated = Signal(object)


def _tab_label(text: str) -> str:
    # Qt reads '&' as a keyboard-mnemonic marker ("Edit & render" would show
    # as "Edit _render"); double it to display a literal ampersand.
    return text.replace("&", "&&")


def _placeholder(m: wl.Mode) -> QWidget:
    w = QWidget()
    w.setObjectName(f"placeholder_{m.key}")
    lay = QVBoxLayout(w)
    lay.addStretch(1)
    title = QLabel(f"<h2>{m.title}</h2>")
    title.setAlignment(Qt.AlignCenter)
    body = QLabel(wl.placeholder_text(m))
    body.setObjectName("placeholder_body")
    body.setWordWrap(True)
    body.setAlignment(Qt.AlignCenter)
    body.setMaximumWidth(560)
    # Centre with stretches, not an alignment flag: a word-wrapped label added
    # with an alignment flag is not given its full height and gets clipped.
    row = QHBoxLayout()
    row.addStretch(1)
    row.addWidget(body, 10)
    row.addStretch(1)
    lay.addWidget(title)
    lay.addLayout(row)
    lay.addStretch(2)
    return w


class WorkspaceWindow(QMainWindow):
    def __init__(self, studio) -> None:
        super().__init__()
        self.studio = studio
        self._shut_down = False
        self._last_saved: str | None = None
        self._lib_sig = None

        # The existing editor, embedded as the "Edit & render" mode.
        self.editor = MainWindow(studio)
        self.editor.setWindowFlags(Qt.Widget)

        self._build_modes()
        self._build_toolbar()
        self._build_docks()
        self._build_shortcuts()

        self._jobs = _JobSignal()
        self._jobs.updated.connect(self._upsert_job)
        studio.queue.add_listener(lambda j: self._jobs.updated.emit(j))
        for job in reversed(studio.store.list_jobs(self.project.id)):
            self._upsert_job(job)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll_project)
        self._timer.start(1000)
        self._poll_project()
        # Characters mode: Character Studio + shot plan (Phase 2 panels).
        from .performance_mount import mount_performance
        self.performance = mount_performance(self)
        self._restore_layout()

    # ---- helpers --------------------------------------------------------
    @property
    def project(self):
        return self.editor.project

    # ---- centre: modes ---------------------------------------------------
    def _build_modes(self) -> None:
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self._tab_index: dict[str, int] = {}
        for m in wl.MODES:
            widget = self.editor if m.built else _placeholder(m)
            label = m.title if m.built else f"{m.title} (not built yet)"
            self._tab_index[m.key] = self.tabs.addTab(widget, _tab_label(label))
            if not m.built:
                self.tabs.setTabToolTip(self._tab_index[m.key],
                                        f"Planned: {m.planned}")
        self.tabs.setCurrentIndex(self._tab_index[wl.DEFAULT_MODE])
        self.setCentralWidget(self.tabs)

    def set_tab_widget(self, key: str, widget: QWidget, title: str | None = None) -> None:
        """Mount point: replace a mode's placeholder with a real panel."""
        if key not in self._tab_index:
            raise KeyError(f"unknown workspace mode: {key}")
        idx = self._tab_index[key]
        current = self.tabs.currentIndex()
        old = self.tabs.widget(idx)
        self.tabs.removeTab(idx)
        self.tabs.insertTab(idx, widget, _tab_label(title or wl.mode(key).title))
        self.tabs.setTabToolTip(idx, "")
        if old is not None and old is not widget and old is not self.editor:
            old.deleteLater()
        self.tabs.setCurrentIndex(current)

    def show_mode(self, key: str) -> None:
        self.tabs.setCurrentIndex(self._tab_index[key])

    # ---- top toolbar ----------------------------------------------------
    def _build_toolbar(self) -> None:
        tb = QToolBar("Production")
        tb.setObjectName("production_toolbar")
        tb.setMovable(False)
        self.addToolBar(Qt.TopToolBarArea, tb)

        self.project_label = QLabel()
        self.save_label = QLabel("Not saved yet")
        self.profile_label = QLabel()
        self.engines_label = QLabel()
        for lbl in (self.project_label, self.save_label, self.profile_label,
                    self.engines_label):
            lbl.setContentsMargins(8, 0, 8, 0)

        self.save_action = QAction("Save", self)
        self.save_action.setShortcut(QKeySequence.Save)
        self.save_action.triggered.connect(self.save_project)
        setup_action = QAction("Setup && diagnostics…", self)
        setup_action.triggered.connect(self._open_setup)

        tb.addWidget(self.project_label)
        tb.addAction(self.save_action)
        tb.addWidget(self.save_label)
        tb.addSeparator()
        tb.addWidget(self.profile_label)
        tb.addSeparator()
        tb.addWidget(self.engines_label)
        tb.addSeparator()
        tb.addAction(setup_action)
        self._refresh_toolbar()

    def _refresh_toolbar(self) -> None:
        self.project_label.setText(f"<b>{self.project.name}</b>")
        eff, _ = self.studio.effective_profile(Profile.AUTO)
        self.profile_label.setText(f"Profile: {eff.value}")
        settings = load_settings(self.studio.config.paths.workspace)
        self.engines_label.setText(wl.engines_summary(
            settings, module_available("nova_studio.adapters.gemini_omni")))
        self.setWindowTitle(wl.title_for(self.project.name))

    def save_project(self) -> None:
        self.studio.save_project(self.project)
        self._last_saved = datetime.now().strftime("%H:%M:%S")
        self.save_label.setText(f"Saved {self._last_saved}")

    def _open_setup(self) -> None:
        self.editor.open_setup()
        self._refresh_toolbar()

    # ---- docks ------------------------------------------------------------
    def _build_docks(self) -> None:
        self.library = QTreeWidget()
        self.library.setHeaderHidden(True)
        self.library.currentItemChanged.connect(self._library_selected)
        self._add_dock("Library", "dock_library", self.library, Qt.LeftDockWidgetArea)

        self.inspector = QTableWidget(0, 2)
        self.inspector.setHorizontalHeaderLabels(["Property", "Value"])
        self.inspector.verticalHeader().setVisible(False)
        self.inspector.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.inspector.setEditTriggers(QTableWidget.NoEditTriggers)
        self._add_dock("Inspector", "dock_inspector", self.inspector,
                       Qt.RightDockWidgetArea)

        self.jobs = QTableWidget(0, 4)
        self.jobs.setHorizontalHeaderLabels(["Job", "State", "Progress", "Details"])
        self.jobs.verticalHeader().setVisible(False)
        self.jobs.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.jobs.setEditTriggers(QTableWidget.NoEditTriggers)
        self._job_rows: dict[str, int] = {}
        self.jobs_dock = self._add_dock("Jobs", "dock_jobs", self.jobs,
                                        Qt.BottomDockWidgetArea)

    def _add_dock(self, title: str, name: str, widget: QWidget, area) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(name)
        dock.setWidget(widget)
        self.addDockWidget(area, dock)
        return dock

    def _poll_project(self) -> None:
        sig = wl.library_signature(self.project)
        if sig == self._lib_sig:
            return
        self._lib_sig = sig
        self._refresh_library()
        self._refresh_toolbar()

    def _refresh_library(self) -> None:
        self.library.clear()
        groups: dict[str, QTreeWidgetItem] = {}
        for entry in wl.library_entries(self.project):
            parent = groups.get(entry.group)
            if parent is None:
                parent = QTreeWidgetItem([entry.group])
                parent.setFlags(parent.flags() & ~Qt.ItemIsSelectable)
                self.library.addTopLevelItem(parent)
                groups[entry.group] = parent
            child = QTreeWidgetItem([entry.label])
            child.setData(0, Qt.UserRole, (entry.group, entry.item_id))
            parent.addChild(child)
        self.library.expandAll()
        if not groups:
            hint = QTreeWidgetItem(["Empty project - import media in Edit & render"])
            hint.setFlags(Qt.NoItemFlags)
            self.library.addTopLevelItem(hint)
        self._show_inspector([])

    def _library_selected(self, current, _previous=None) -> None:
        ref = current.data(0, Qt.UserRole) if current is not None else None
        rows = wl.inspector_rows(self.project, *ref) if ref else []
        self._show_inspector(rows)

    def _show_inspector(self, rows: list[tuple[str, str]]) -> None:
        self.inspector.setRowCount(len(rows))
        for i, (k, v) in enumerate(rows):
            self.inspector.setItem(i, 0, QTableWidgetItem(k))
            self.inspector.setItem(i, 1, QTableWidgetItem(v))

    def _upsert_job(self, job) -> None:
        row = self._job_rows.get(job.id)
        if row is None:
            row = 0
            self.jobs.insertRow(0)
            self._job_rows = {jid: r + 1 for jid, r in self._job_rows.items()}
            self._job_rows[job.id] = 0
        for col, text in enumerate(wl.job_row(job)):
            self.jobs.setItem(row, col, QTableWidgetItem(text))

    # ---- shortcuts & layout -----------------------------------------------
    def _build_shortcuts(self) -> None:
        for n, m in enumerate(wl.MODES, start=1):
            act = QAction(self)
            act.setShortcut(QKeySequence(f"Ctrl+{n}"))
            act.triggered.connect(lambda _=False, k=m.key: self.show_mode(k))
            self.addAction(act)

    def _restore_layout(self) -> None:
        s = load_settings(self.studio.config.paths.workspace)
        if s.workspace_geometry:
            self.restoreGeometry(QByteArray.fromBase64(s.workspace_geometry.encode()))
        else:
            self.resize(1400, 860)
        if not s.workspace_state:
            # First launch: a compact job queue, so the modes get the space.
            self.resizeDocks([self.jobs_dock], [170], Qt.Vertical)
        if s.workspace_state:
            self.restoreState(QByteArray.fromBase64(s.workspace_state.encode()))

    def save_layout(self) -> None:
        ws = self.studio.config.paths.workspace
        s = load_settings(ws)
        s.workspace_geometry = bytes(self.saveGeometry().toBase64()).decode()
        s.workspace_state = bytes(self.saveState().toBase64()).decode()
        save_settings(ws, s)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt signature)
        self._timer.stop()
        try:
            # Character, dialogue and shot edits live in the project; keep
            # them even if Save was never pressed.
            self.studio.save_project(self.project)
        except Exception as exc:  # never block closing, but say so
            QMessageBox.warning(self, "NOVA", f"Could not save the project: {exc}")
        try:
            self.save_layout()
        except OSError as exc:
            QMessageBox.warning(self, "NOVA", f"Could not save the window layout: {exc}")
        # The embedded editor does not receive this event; shut the core down
        # here, exactly once.
        if not self._shut_down:
            self._shut_down = True
            self.studio.shutdown()
        super().closeEvent(event)
