"""Drives the real Character Studio and shot plan widgets offscreen.

Run by test_panels_qt.py in its own process, because other UI tests replace
PySide6 with a stub for the rest of their pytest process. Exit code 77 means
PySide6 is not installed.
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import importlib.util

if importlib.util.find_spec("PySide6") is None:
    sys.exit(77)
# Installed but unable to load (e.g. missing system libraries) is a failure.
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QMessageBox

from nova_studio.adapters.gemini_omni import GeminiOmniEngine
from nova_studio.models.project import Project
from nova_studio.performance.engines import EngineRegistry
from nova_studio.ui.character_studio import CharacterStudioPanel
from nova_studio.ui.shot_plan import ShotPlanPanel

app = QApplication.instance() or QApplication([])
warnings = []
QMessageBox.warning = staticmethod(lambda *a, **k: warnings.append(a[2]))

tmp = Path(tempfile.mkdtemp())
img = tmp / "maya.png"
q = QImage(64, 64, QImage.Format_RGB32); q.fill(QColor("orange")); q.save(str(img))

project = Project(name="t")
changes = []
cs = CharacterStudioPanel(project, on_changed=lambda: changes.append(1))
assert not cs.generate_btn.isEnabled() and "none is included" in cs.generate_btn.toolTip()
assert not cs.upload_btn.isEnabled()          # no character yet

cs.name_edit.setText("Maya"); cs.add_btn.click()
cs.name_edit.setText("Leo"); cs.add_btn.click()
assert [c.id for c in project.characters] == ["maya", "leo"]
cs.char_list.setCurrentRow(0)
assert cs.current_character().id == "maya"
assert cs.add_reference_images([img])
maya = project.character("maya")
assert len(maya.candidates) == 1 and cs.preview.pixmap() and not cs.preview.pixmap().isNull()
assert cs.approve_btn.isEnabled() and not cs.lock_btn.isEnabled()
cs.approve_btn.click()
assert project.character("maya").approved.version == 1
assert cs.lock_btn.isEnabled(); cs.lock_btn.click()
assert project.character("maya").locked
# Character order is kept when a character is updated.
assert [c.id for c in project.characters] == ["maya", "leo"]
# A bad upload is refused with a message, not added.
assert not cs.add_reference_images([tmp / "nope.txt"]) and warnings
assert len(project.character("maya").candidates) == 1
assert changes

# Shot plan with Omni switched off: the shot is blocked and says why.
omni = GeminiOmniEngine(api_key_provider=lambda: "", cloud_enabled=lambda: False)
sp = ShotPlanPanel(project, EngineRegistry([omni.spec()]))
combo = sp.engine_combos["video"]
assert "unavailable" in combo.itemText(1)
combo.setCurrentIndex(1)
assert project.engine_selection.video == "gemini-omni-flash"
sp.cast_list.item(0).setSelected(True)
sp.add_shot_btn.click()
assert project.shots[0].character_ids == ["maya"]
sp.line_edit.setText("Hello there."); sp.add_line_btn.click()
assert project.shots[0].dialogue_line_ids == [project.dialogue[0].id]
assert "Blocked" in sp.plan_label.text() and "switched off" in sp.plan_label.text()
sp.pin_btn.click()
pin = project.shots[0].pins[0]
assert pin.character_id == "maya" and pin.version == 1

# Everything survives a save and reload.
again = Project.model_validate_json(project.model_dump_json())
assert again.shots[0].pins[0].reference_id == pin.reference_id

# Voice picker: choosing a voice is saved and logged; a missing voice is kept.
cs2 = CharacterStudioPanel(project, voice_choices=lambda: [
    ("voice:piper", "en_US-amy-medium.onnx", "en_US-amy-medium.onnx (Piper)")])
cs2.char_list.setCurrentRow(0)
assert cs2.voice_combo.count() == 2
cs2.voice_combo.setCurrentIndex(1)
maya = project.character("maya")
assert (maya.voice.engine_id, maya.voice.voice_id) == ("voice:piper", "en_US-amy-medium.onnx")
assert maya.history[-1].action == "voice_changed" and maya.locked
cs3 = CharacterStudioPanel(project, voice_choices=lambda: [])
cs3.char_list.setCurrentRow(0)
assert "not installed" in cs3.voice_combo.currentText()
assert "No voices are installed" in cs3.voice_note.text()
assert project.character("maya").voice.voice_id == "en_US-amy-medium.onnx"
print("ok")
