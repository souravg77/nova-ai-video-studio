"""Undo/redo across panels and autosave, in the real workspace (headless)."""
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

SCRIPT = textwrap.dedent('''
    import json
    from PySide6.QtWidgets import QApplication
    from nova_studio.core.studio import Studio
    from nova_studio.ui import workspace as ws_mod
    from nova_studio.ui.workspace import WorkspaceWindow

    ws_mod.AUTOSAVE_SECONDS = 2          # speed up autosave for the test
    app = QApplication([])
    studio = Studio()
    win = WorkspaceWindow(studio)
    out = {"undo_enabled_at_start": win.undo_action.isEnabled()}
    text = chr(10).join(["INT. HALL - NIGHT", "", "AVA", "Hello there.", ""])

    # A breakdown in the Script tab is one undoable change.
    win.script.editor.setPlainText(text)
    win.script.break_down()
    win._poll_project(); app.processEvents()
    out["after_breakdown"] = [len(win.project.dialogue), len(win.project.characters)]
    out["undo_enabled"] = win.undo_action.isEnabled()

    # Undo restores the empty project in every panel; redo brings it back.
    win.undo(); app.processEvents()
    out["after_undo"] = [len(win.project.dialogue), len(win.project.characters),
                         win.script.editor.toPlainText(), win.script.table.rowCount(),
                         win.locations.list.count()]
    win.redo(); app.processEvents()
    out["after_redo"] = [len(win.project.dialogue), win.script.table.rowCount(),
                         win.locations.list.count(), win.script.editor.toPlainText() == text]

    # Autosave: unsaved edits are written after AUTOSAVE_SECONDS polls.
    win._poll_project(); win._poll_project(); app.processEvents()
    out["save_label"] = win.save_label.text()
    saved = studio.store.load_project(win.project.id)
    out["saved_has_dialogue"] = len(saved.dialogue)
    out["dirty_after_autosave"] = win.history.dirty
    win.close(); app.processEvents()
    print("RESULT " + json.dumps(out))
''')


def test_undo_redo_and_autosave(tmp_path):
    probe = subprocess.run([sys.executable, "-c", "import PySide6.QtWidgets"],
                           capture_output=True)
    if probe.returncode != 0:
        pytest.skip("real PySide6 not installed")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=str(ROOT / "src"),
               NOVA_STUDIO_HOME=str(tmp_path / "home"))
    proc = subprocess.run([sys.executable, "-c", SCRIPT], env=env,
                          capture_output=True, text=True, timeout=180)
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, proc.stdout + proc.stderr
    out = json.loads(lines[0][len("RESULT "):])

    assert out["undo_enabled_at_start"] is False
    assert out["after_breakdown"] == [1, 1] and out["undo_enabled"]
    assert out["after_undo"] == [0, 0, "", 0, 0]
    assert out["after_redo"] == [1, 1, 1, True]
    assert out["save_label"].startswith("Autosaved")
    assert out["saved_has_dialogue"] == 1 and out["dirty_after_autosave"] is False
