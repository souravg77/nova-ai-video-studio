"""Drives the real Scene panel offscreen (run by test_scene_qt.py). 77 = no PySide6."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import importlib.util

if importlib.util.find_spec("PySide6") is None:
    sys.exit(77)
from PySide6.QtWidgets import QApplication, QMessageBox

from nova_studio.generate.versions import Version, VersionStore
from nova_studio.media.probe import check_tool, ffmpeg_path
from nova_studio.models.project import Project
from nova_studio.performance.planner import Shot
from nova_studio.ui.scene_panel import ScenePanel

app = QApplication.instance() or QApplication([])
warnings = []
QMessageBox.warning = staticmethod(lambda *a, **k: warnings.append(a[2]))
tmp = Path(tempfile.mkdtemp())
have_ffmpeg = check_tool("ffmpeg").ok and check_tool("ffprobe").ok

p = Project(name="t")
p.shots = [Shot(id="s1", duration_s=4.0), Shot(id="s2", duration_s=3.0)]
gen = tmp / "gen"
sp = ScenePanel(p, gen, lambda: tmp / "out" / "t_scene.mp4")
assert sp.cut_list.count() == 2 and not sp.export_btn.isEnabled()
assert "2 without a clip" in sp.total_label.text()

src = tmp / "a.mp4"
if have_ffmpeg:
    subprocess.run([ffmpeg_path(), "-y", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc=size=320x180:rate=24:duration=3", "-f", "lavfi", "-i",
                    "sine=duration=3", "-shortest", str(src)], check=True)
else:
    src.write_bytes(b"x")
store = VersionStore(gen)
v = Version(id="ver-1", shot_id="s2", mode="text", prompt="A door.", ok=True,
            path=str(src), duration_s=3.0, has_audio=True)
store.add(v); store.choose("s2", "ver-1")
sp.refresh()
assert sp.cut_list.item(1).text().startswith("2. s2: clip 0.0-3.0 s, with sound")
assert sp.export_btn.isEnabled()
# Reorder: s2 first.
sp.cut_list.setCurrentRow(1)
assert sp.up_btn.isEnabled() and not sp.down_btn.isEnabled()
sp.up_btn.click()
assert [c.shot_id for c in sp.cuts] == ["s2", "s1"] and sp.cut_list.currentRow() == 0
# Trim the clip; a bad trim is refused with a message.
sp.in_spin.setValue(0.5); sp.out_spin.setValue(2.5); sp.trim_btn.click()
assert sp.cuts[0].duration_s == 2.0
sp.in_spin.setValue(2.4); sp.out_spin.setValue(2.5)
sp.trim_btn.click()
assert warnings and sp.cuts[0].duration_s == 2.0
# The still/card shot can't be trimmed.
sp.cut_list.setCurrentRow(1)
assert not sp.trim_btn.isEnabled() and "No clip chosen" in sp.detail.text()
if have_ffmpeg:
    assert sp.export()
    sp.wait()
    assert sp.last_export.ok, sp.last_export.message
    assert "s1" in sp.status.text() and sp.open_btn.isEnabled()
    assert (tmp / "out" / "t_scene.mp4").is_file()
print("ok")
