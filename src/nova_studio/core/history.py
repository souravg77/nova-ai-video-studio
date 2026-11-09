"""Project-wide undo/redo and autosave state (roadmap M2: undo, autosave).

Snapshot-based: after any change the whole project is recorded (as its JSON
manifest), so every panel - script, direction, locations, characters, shots,
the editor - gets undo without each one implementing commands. Undo restores
the project *in place* (same object), because every panel holds a reference
to it. Snapshots are compared by content, so idle polling records nothing.
"""
from __future__ import annotations

import hashlib
from typing import Optional

from ..models.project import Project

DEFAULT_LIMIT = 100


def fingerprint(project: Project) -> str:
    """Content hash of the project, ignoring the 'last touched' time."""
    data = project.model_dump_json(exclude={"updated_at"})
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


class ProjectHistory:
    def __init__(self, project: Project, limit: int = DEFAULT_LIMIT) -> None:
        self.project = project
        self.limit = limit
        self._undo: list[str] = []      # JSON snapshots, oldest first; last = current
        self._redo: list[str] = []
        self._hashes: list[str] = []
        self.saved_hash: Optional[str] = None
        self.record()

    # ---- recording ---------------------------------------------------------
    def record(self) -> bool:
        """Snapshot the project if it changed since the last snapshot."""
        h = fingerprint(self.project)
        if self._hashes and self._hashes[-1] == h:
            return False
        self._undo.append(self.project.model_dump_json())
        self._hashes.append(h)
        self._redo.clear()
        if len(self._undo) > self.limit + 1:
            del self._undo[0], self._hashes[0]
        return True

    @property
    def can_undo(self) -> bool:
        return len(self._undo) > 1

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    # ---- moving through history ------------------------------------------------
    def _restore(self, snapshot: str) -> None:
        restored = Project.model_validate_json(snapshot)
        for name in Project.model_fields:
            setattr(self.project, name, getattr(restored, name))

    def undo(self) -> bool:
        self.record()                     # never lose an unrecorded edit
        if not self.can_undo:
            return False
        self._redo.append(self._undo.pop())
        self._hashes.pop()
        self._restore(self._undo[-1])
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        snap = self._redo.pop()
        self._restore(snap)
        self._undo.append(snap)
        self._hashes.append(fingerprint(self.project))
        return True

    # ---- autosave bookkeeping -----------------------------------------------------
    @property
    def dirty(self) -> bool:
        return fingerprint(self.project) != self.saved_hash

    def mark_saved(self) -> None:
        self.saved_hash = fingerprint(self.project)
