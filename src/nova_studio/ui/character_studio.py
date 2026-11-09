"""Character Studio panel: create characters, add reference images, approve,
lock and unlock designs.

Every change goes through ``performance.characters`` so the identity rules
(approval never overwritten by new candidates, locked designs stay locked,
unlocks are logged) hold here exactly as they do in tests.

Designs can only be uploaded for now: no image engine ships in this build,
so the Generate button stays disabled and says why.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFileDialog, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidget, QMessageBox, QPushButton, QSplitter, QVBoxLayout, QWidget)

from ..performance import characters as ident
from . import performance_view as view


class CharacterStudioPanel(QWidget):
    def __init__(self, project, on_changed: Optional[Callable[[], None]] = None,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.project = project
        self._on_changed = on_changed or (lambda: None)
        self._build()
        self.refresh()

    # -- layout --------------------------------------------------------------
    def _build(self) -> None:
        root = QHBoxLayout(self)
        split = QSplitter(Qt.Horizontal)
        root.addWidget(split)

        left = QWidget(); lv = QVBoxLayout(left)
        lv.addWidget(QLabel("Characters"))
        self.char_list = QListWidget()
        self.char_list.currentRowChanged.connect(lambda _r: self._show_character())
        lv.addWidget(self.char_list)
        row = QHBoxLayout()
        self.name_edit = QLineEdit(); self.name_edit.setPlaceholderText("New character name")
        self.add_btn = QPushButton("Add")
        self.add_btn.clicked.connect(self._add_character)
        self.name_edit.returnPressed.connect(self._add_character)
        row.addWidget(self.name_edit); row.addWidget(self.add_btn)
        lv.addLayout(row)
        split.addWidget(left)

        mid = QWidget(); mv = QVBoxLayout(mid)
        cand_box = QGroupBox("Design candidates"); cv = QVBoxLayout(cand_box)
        self.cand_list = QListWidget()
        self.cand_list.currentRowChanged.connect(lambda _r: self._show_candidate())
        cv.addWidget(self.cand_list)
        r1 = QHBoxLayout()
        self.upload_btn = QPushButton("Upload reference image…")
        self.upload_btn.clicked.connect(self._upload)
        self.generate_btn = QPushButton("Generate designs")
        self.generate_btn.setEnabled(False)
        self.generate_btn.setToolTip(view.NO_IMAGE_ENGINE)
        r1.addWidget(self.upload_btn); r1.addWidget(self.generate_btn)
        cv.addLayout(r1)
        r2 = QHBoxLayout()
        self.approve_btn = QPushButton("Approve design")
        self.approve_btn.clicked.connect(self._approve)
        self.reject_btn = QPushButton("Reject")
        self.reject_btn.clicked.connect(lambda: self._set_rejected(True))
        self.restore_btn = QPushButton("Restore")
        self.restore_btn.clicked.connect(lambda: self._set_rejected(False))
        for b in (self.approve_btn, self.reject_btn, self.restore_btn):
            r2.addWidget(b)
        cv.addLayout(r2)
        self.preview = QLabel("No candidate selected")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(220)
        cv.addWidget(self.preview)
        mv.addWidget(cand_box)
        split.addWidget(mid)

        right = QWidget(); rv = QVBoxLayout(right)
        id_box = QGroupBox("Identity"); iv = QVBoxLayout(id_box)
        self.status_label = QLabel(""); self.status_label.setWordWrap(True)
        iv.addWidget(self.status_label)
        note = QLabel(view.REFERENCE_NOTE); note.setWordWrap(True)
        iv.addWidget(note)
        r3 = QHBoxLayout()
        self.lock_btn = QPushButton("Lock identity")
        self.lock_btn.clicked.connect(self._lock)
        self.unlock_btn = QPushButton("Unlock…")
        self.unlock_btn.clicked.connect(self._unlock)
        r3.addWidget(self.lock_btn); r3.addWidget(self.unlock_btn)
        iv.addLayout(r3)
        rv.addWidget(id_box)
        hist_box = QGroupBox("History"); hv = QVBoxLayout(hist_box)
        self.history_list = QListWidget()
        hv.addWidget(self.history_list)
        rv.addWidget(hist_box)
        split.addWidget(right)

    # -- state ---------------------------------------------------------------
    def current_character(self) -> Optional[ident.Character]:
        row = self.char_list.currentRow()
        chars = self.project.characters
        return chars[row] if 0 <= row < len(chars) else None

    def current_candidate(self) -> Optional[ident.Candidate]:
        c = self.current_character()
        row = self.cand_list.currentRow()
        return c.candidates[row] if c and 0 <= row < len(c.candidates) else None

    def refresh(self, select_id: Optional[str] = None) -> None:
        keep = select_id or (self.current_character().id
                             if self.current_character() else None)
        self.char_list.blockSignals(True)
        self.char_list.clear()
        for c in self.project.characters:
            self.char_list.addItem(view.character_row(c))
        ids = [c.id for c in self.project.characters]
        self.char_list.setCurrentRow(ids.index(keep) if keep in ids else
                                     (0 if ids else -1))
        self.char_list.blockSignals(False)
        self._show_character()

    def _show_character(self, cand_row: Optional[int] = None) -> None:
        c = self.current_character()
        self.cand_list.blockSignals(True)
        self.cand_list.clear()
        self.history_list.clear()
        if c is None:
            self.status_label.setText("Add a character to start.")
        else:
            for cand in c.candidates:
                self.cand_list.addItem(view.candidate_row(c, cand))
            for h in view.history_rows(c):
                self.history_list.addItem(h)
            self.status_label.setText(
                f"{c.name}: {view.character_status(c)}\n{view.readiness_text(c)}")
            if c.candidates:
                self.cand_list.setCurrentRow(
                    cand_row if cand_row is not None and cand_row < len(c.candidates)
                    else len(c.candidates) - 1)
        self.cand_list.blockSignals(False)
        self.upload_btn.setEnabled(c is not None)
        self._show_candidate()

    def _show_candidate(self) -> None:
        c, cand = self.current_character(), self.current_candidate()
        acts = view.candidate_actions(c, cand)
        self.approve_btn.setEnabled(acts.approve)
        self.approve_btn.setToolTip(acts.approve_hint)
        self.reject_btn.setEnabled(acts.reject)
        self.restore_btn.setEnabled(acts.restore)
        self.lock_btn.setEnabled(acts.lock)
        self.unlock_btn.setEnabled(acts.unlock)
        if cand is None:
            self.preview.setPixmap(QPixmap())
            self.preview.setText("No candidate selected")
            return
        pix = QPixmap(cand.image_path)
        if pix.isNull():
            self.preview.setPixmap(QPixmap())
            self.preview.setText(f"Can't show {Path(cand.image_path).name} "
                                 f"(missing or unreadable).")
        else:
            self.preview.setText("")
            self.preview.setPixmap(pix.scaled(320, 320, Qt.KeepAspectRatio,
                                              Qt.SmoothTransformation))

    # -- actions -------------------------------------------------------------
    def _apply(self, fn, *args) -> bool:
        c = self.current_character()
        if c is None:
            return False
        row = self.cand_list.currentRow()
        try:
            updated = fn(c, *args)
        except (ident.IdentityError, ValueError) as exc:
            QMessageBox.warning(self, "Character Studio", str(exc))
            return False
        self.project.put_character(updated)
        self.refresh(select_id=updated.id)
        self._show_character(cand_row=row if row >= 0 else None)
        self._on_changed()
        return True

    def _add_character(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            return
        cid = view.new_character_id(name, self.project.characters)
        self.project.put_character(ident.create_character(
            cid, name, getattr(self.project, "language", "en")))
        self.name_edit.clear()
        self.refresh(select_id=cid)
        self._on_changed()

    def add_reference_images(self, paths: list[Path]) -> bool:
        try:
            cands = [view.uploaded_candidate(Path(p)) for p in paths]
        except ValueError as exc:
            QMessageBox.warning(self, "Character Studio", str(exc))
            return False
        c = self.current_character()
        ok = self._apply(ident.add_candidates, cands)
        if ok and c is not None:
            self._show_character(cand_row=len(c.candidates))  # first new one
        return ok

    def _upload(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "Choose reference images", "",
            "Images (*.png *.jpg *.jpeg *.webp)")
        if files:
            self.add_reference_images([Path(f) for f in files])

    def _approve(self) -> None:
        cand = self.current_candidate()
        if cand is not None:
            self._apply(ident.approve_candidate, cand.id)

    def _set_rejected(self, rejected: bool) -> None:
        cand = self.current_candidate()
        if cand is not None:
            self._apply(ident.set_candidate_rejected, cand.id, rejected)

    def _lock(self) -> None:
        self._apply(ident.lock_identity)

    def _unlock(self) -> None:
        reason, ok = QInputDialog.getText(
            self, "Unlock identity",
            "Why are you unlocking this character? (saved in its history)")
        if ok and reason.strip():
            self._apply(ident.unlock_identity, reason)
