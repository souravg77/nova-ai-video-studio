"""Close the real workspace and open it again: the work is still there.

Runs in a subprocess (other UI tests replace PySide6 with a stub).
"""
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

SCRIPT = textwrap.dedent('''
    import json, sys
    from pathlib import Path
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtWidgets import QApplication
    from nova_studio.core.studio import Studio
    from nova_studio.models.project import Asset, AssetKind, Scene
    from nova_studio.ui.workspace import WorkspaceWindow

    tmp = Path(sys.argv[1])
    app = QApplication([])
    img = tmp / "maya.png"
    q = QImage(32, 32, QImage.Format_RGB32); q.fill(QColor("teal")); q.save(str(img))
    out = {}

    s = Studio(); w = WorkspaceWindow(s)
    pid = w.project.id
    cs = w.performance.characters
    cs.name_edit.setText("Maya"); cs.add_btn.click()
    cs.add_reference_images([img]); cs.approve_btn.click()
    # Saved as soon as it changes, before any explicit Save.
    out["saved_on_change"] = [c.name for c in s.store.load_project(pid).characters]
    # A scene added behind the editor's back is still saved on close.
    a = w.project.add_asset(Asset(kind=AssetKind.IMAGE, path=str(img), width=32, height=32))
    w.project.add_scene(Scene(title="Opening", visual_asset_id=a.id, duration_s=3.0))
    w.close(); app.processEvents()
    img.unlink()                                  # original reference removed

    s2 = Studio(); w2 = WorkspaceWindow(s2); app.processEvents()
    out["same_project"] = w2.project.id == pid
    out["projects"] = len(s2.store.list_projects())
    out["characters"] = [c.name for c in w2.project.characters]
    ref = Path(w2.project.characters[0].approved.image_path)
    out["reference_kept"] = ref.exists() and pid in str(ref)
    out["scene_rows"] = w2.editor.scene_list.count()
    out["asset_rows"] = w2.editor.asset_list.count()
    out["name_field"] = w2.editor.name_edit.text()
    w2.close(); app.processEvents()
    print("RESULT " + json.dumps(out))
''')


def test_work_survives_closing_and_reopening(tmp_path):
    probe = subprocess.run([sys.executable, "-c", "import PySide6.QtWidgets"],
                           capture_output=True)
    if probe.returncode != 0:
        pytest.skip("real PySide6 not installed")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen",
               PYTHONPATH=str(ROOT / "src"), NOVA_STUDIO_HOME=str(tmp_path / "home"))
    env.pop("NOVA_GEMINI_API_KEY", None)
    proc = subprocess.run([sys.executable, "-c", SCRIPT, str(tmp_path)], env=env,
                          capture_output=True, text=True, timeout=180)
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, proc.stdout + proc.stderr
    out = json.loads(lines[0][len("RESULT "):])
    assert out["saved_on_change"] == ["Maya"]
    assert out["same_project"] and out["projects"] == 1
    assert out["characters"] == ["Maya"] and out["reference_kept"]
    assert out["scene_rows"] == 1 and out["asset_rows"] == 1
    assert out["name_field"] == "Untitled Project"
