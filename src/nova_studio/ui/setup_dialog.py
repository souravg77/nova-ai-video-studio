"""First-launch Setup & Diagnostics dialog (roadmap M1).

Shows the measured state of this PC (core.setup_check) and the few settings
the user can change. Controls whose backend is not in this build are shown
disabled with the reason, never as working switches.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from ..core.setup_check import (CheckItem, Status, module_available,
                                overall_status, run_setup_checks)
from ..settings import AppSettings, load_settings, save_settings

_MARK = {Status.OK: "✔", Status.WARN: "⚠", Status.FAIL: "✖", Status.INFO: "ℹ"}
_COLOR = {Status.OK: "#2e7d32", Status.WARN: "#b26a00",
          Status.FAIL: "#c62828", Status.INFO: "#1565c0"}
_OVERALL = {
    Status.OK: "Everything NOVA needs is in place.",
    Status.WARN: "NOVA works, but some features are limited (see ⚠ below).",
    Status.FAIL: "Something NOVA needs is missing (see ✖ below).",
}


def item_html(item: CheckItem) -> str:
    """Render one check as rich text (escaped; detail may contain paths)."""
    from html import escape
    detail = escape(item.detail).replace("\n", "<br>")
    html = (f"<span style='color:{_COLOR[item.status]};font-weight:bold'>"
            f"{_MARK[item.status]} {escape(item.title)}</span><br>{detail}")
    if item.fix:
        html += f"<br><i>{escape(item.fix).replace(chr(10), '<br>')}</i>"
    return html


class SetupDialog(QDialog):
    def __init__(self, studio, first_run: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.studio = studio
        self.workspace = Path(studio.config.paths.workspace)
        self.settings: AppSettings = load_settings(self.workspace)
        self._initial_models_dir = self.settings.models_dir
        self.setWindowTitle("NOVA - Setup & diagnostics")
        self.resize(720, 640)

        root = QVBoxLayout(self)
        if first_run:
            welcome = QLabel(
                "<b>Welcome to NOVA.</b> This is what NOVA measured on this PC. "
                "You can reopen this any time from <i>Setup &amp; diagnostics…</i>")
            welcome.setWordWrap(True)
            root.addWidget(welcome)

        self.overall = QLabel()
        self.overall.setWordWrap(True)
        root.addWidget(self.overall)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._checks_host = QWidget()
        self._checks_layout = QVBoxLayout(self._checks_host)
        scroll.setWidget(self._checks_host)
        root.addWidget(scroll, 1)

        # ---- Models folder ------------------------------------------------
        models_box = QGroupBox("Models folder (large AI model files)")
        mv = QVBoxLayout(models_box)
        row = QHBoxLayout()
        self.models_edit = QLineEdit(str(studio.config.paths.models))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_models)
        default_btn = QPushButton("Use default")
        default_btn.clicked.connect(self._default_models)
        row.addWidget(self.models_edit, 1)
        row.addWidget(browse)
        row.addWidget(default_btn)
        mv.addLayout(row)
        self.models_note = QLabel("A new folder takes effect after NOVA restarts.")
        self.models_note.setWordWrap(True)
        mv.addWidget(self.models_note)
        root.addWidget(models_box)

        # ---- Optional engines ---------------------------------------------
        eng_box = QGroupBox("Optional engines")
        ev = QVBoxLayout(eng_box)
        # Checkbox text cannot wrap, so keep it short and explain below.
        not_in_build = " (not included in this build yet)"
        self.gemini_check = QCheckBox("Gemini Omni Flash - cloud engine")
        self.gemini_check.setChecked(self.settings.cloud.gemini_enabled)
        if not module_available("nova_studio.adapters.gemini_omni"):
            self.gemini_check.setEnabled(False)
            self.gemini_check.setChecked(False)
            self.gemini_check.setText(self.gemini_check.text() + not_in_build)
        ev.addWidget(self.gemini_check)
        ev.addWidget(self._note(
            "Off by default. When on, prompts and attached media for jobs you "
            "run with it are sent to Google using your own API key."))
        self.preview_check = QCheckBox("Experimental local video preview (CPU)"
                                       + not_in_build)
        self.preview_check.setEnabled(False)
        self.preview_check.setChecked(False)
        ev.addWidget(self.preview_check)
        ev.addWidget(self._note(
            "Short, low-resolution motion previews made on this PC. "
            "Personal use only: the model's licence does not allow commercial use."))
        root.addWidget(eng_box)

        # ---- Buttons --------------------------------------------------------
        btns = QHBoxLayout()
        recheck = QPushButton("Check again")
        recheck.clicked.connect(lambda: self.refresh(refresh=True))
        done = QPushButton("Save && close")
        done.setDefault(True)
        done.clicked.connect(self.accept)
        btns.addWidget(recheck)
        btns.addStretch(1)
        btns.addWidget(done)
        root.addLayout(btns)

        self.refresh()

    # ------------------------------------------------------------------
    @staticmethod
    def _note(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setContentsMargins(22, 0, 0, 6)
        return lbl

    def refresh(self, refresh: bool = False) -> list[CheckItem]:
        items = run_setup_checks(self.studio.config, self.studio.report,
                                 self.studio.capability, self.settings,
                                 refresh=refresh)
        while self._checks_layout.count():
            w = self._checks_layout.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        for item in items:
            lbl = QLabel(item_html(item))
            lbl.setTextFormat(Qt.RichText)
            lbl.setWordWrap(True)
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self._checks_layout.addWidget(lbl)
        self._checks_layout.addStretch(1)
        overall = overall_status(items)
        self.overall.setText(
            f"<span style='color:{_COLOR[overall]};font-weight:bold'>"
            f"{_MARK[overall]} {_OVERALL[overall]}</span>")
        self.items = items
        return items

    def _browse_models(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose models folder",
                                             self.models_edit.text())
        if d:
            self.models_edit.setText(d)

    def _default_models(self) -> None:
        self.models_edit.setText(str(self.workspace / "models"))

    def collect_settings(self) -> AppSettings:
        """The settings as edited in the dialog (not yet saved)."""
        s = self.settings.model_copy(deep=True)
        chosen = self.models_edit.text().strip()
        default = str(self.workspace / "models")
        s.models_dir = None if not chosen or Path(chosen) == Path(default) else chosen
        if self.gemini_check.isEnabled():
            s.cloud.gemini_enabled = self.gemini_check.isChecked()
        s.first_run_complete = True
        return s

    def accept(self) -> None:  # noqa: D401 (Qt override)
        self.settings = self.collect_settings()
        save_settings(self.workspace, self.settings)
        super().accept()

    def reject(self) -> None:  # noqa: D401 (Qt override)
        # Closing without saving still counts as "seen", so the welcome does
        # not reappear on every launch; other edits are discarded.
        if not self.settings.first_run_complete:
            seen = self.settings.model_copy(deep=True)
            seen.first_run_complete = True
            save_settings(self.workspace, seen)
            self.settings = seen
        super().reject()

    @property
    def restart_needed(self) -> bool:
        return self.settings.models_dir != self._initial_models_dir
