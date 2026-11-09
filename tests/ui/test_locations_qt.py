"""The real PySide6 Locations panel, driven headless."""
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
    from PIL import Image
    from PySide6.QtWidgets import QApplication
    from nova_studio.director.breakdown import apply_breakdown
    from nova_studio.director.parser import parse_script
    from nova_studio.models.project import Project
    from nova_studio.ui.locations_panel import LocationsPanel

    tmp = Path(sys.argv[1]); tmp.mkdir(parents=True, exist_ok=True)
    img = tmp / "hall.png"; Image.new("RGB", (64, 40), (90, 60, 30)).save(img)
    app = QApplication([])
    out = {}
    p = Project(name="Loc test")
    text = chr(10).join(["INT. GRAND HALL - NIGHT", "", "Rain.", "",
                         "EXT. GARDEN - DAWN", "", "Birds.", ""])
    apply_breakdown(p, parse_script(text), text)
    panel = LocationsPanel(p, export_dir=tmp)
    out["items"] = [panel.list.item(i).text() for i in range(panel.list.count())]
    panel.toggle_approval()
    out["refused"] = panel.status.text()
    out["set_ok"] = panel.set_slot("front", str(img))
    panel.toggle_approval()
    out["approved"] = p.director.locations[0].approved
    out["item0"] = panel.list.item(0).text()
    out["slot_buttons_locked"] = not any(b.isEnabled() for b in panel._slot_buttons)
    out["sheet"] = panel.export_sheet()
    print("RESULT " + json.dumps(out))
''')


def test_locations_panel(tmp_path):
    probe = subprocess.run([sys.executable, "-c", "import PySide6.QtWidgets"],
                           capture_output=True)
    if probe.returncode != 0:
        pytest.skip("real PySide6 not installed")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=str(ROOT / "src"))
    proc = subprocess.run([sys.executable, "-c", SCRIPT, str(tmp_path)], env=env,
                          capture_output=True, text=True, timeout=120)
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, proc.stdout + proc.stderr
    out = json.loads(lines[0][len("RESULT "):])
    assert out["items"] == ["GRAND HALL  [draft]", "GARDEN  [draft]"]
    assert "frontal view" in out["refused"]
    assert out["set_ok"] and out["approved"]
    assert out["item0"] == "GRAND HALL  [approved v1]"
    assert out["slot_buttons_locked"]
    assert Path(out["sheet"]).name == "GRAND HALL_sheet.png" and Path(out["sheet"]).is_file()
