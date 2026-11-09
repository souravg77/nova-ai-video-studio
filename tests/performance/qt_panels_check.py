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
assert "Blocked" in sp.plan_text.toPlainText() and "switched off" in sp.plan_text.toPlainText()
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

# Voicing from the shot plan: Maya's line uses her voice; nothing else is used.
from nova_studio.adapters.base import AdapterResult
from nova_studio.performance.voicing import DialogueVoicer

class _TTS:
    def __init__(self, p): self.p = p
    def run(self, params):
        Path(params["out_path"]).write_bytes(b"RIFF")
        return AdapterResult(True, metrics={"duration_s": 1.0})

vdir = tmp / "tts"; vdir.mkdir()
(vdir / "en_US-amy-medium.onnx").write_bytes(b"x")
audio = tmp / "dialogue"
sp2 = ShotPlanPanel(project, EngineRegistry([omni.spec()]),
                    voicer=DialogueVoicer(vdir, _TTS), audio_dir=audio)
assert sp2.voice_btn.isEnabled()
sp2.voice_btn.click()
assert [t.ok for t in sp2.last_takes] == [True]
assert "Voiced 1 of 1" in sp2.voice_label.text()
assert (audio / "takes.json").exists()
assert not ShotPlanPanel(project, EngineRegistry([])).voice_btn.isEnabled()
print("ok")

# Timing from the recorded take, re-voicing one line, and fitting the shot.
shot = project.shots[0]
assert "[0.4-1.4 s]" in sp2.line_list.item(0).text(), sp2.line_list.item(0).text()
assert "need 2.0 s" in sp2.timing_label.text() and "6 s" in sp2.timing_label.text()
assert sp2.fit_btn.isEnabled() and not sp2.revoice_btn.isEnabled()
sp2.line_list.setCurrentRow(0)
assert sp2.revoice_btn.isEnabled()
sp2.revoice_btn.click()
assert [t.line_id for t in sp2.last_takes] == [shot.dialogue_line_ids[0]]
assert sp2.line_list.currentRow() == 0
sp2.fit_btn.click()
assert project.shots[0].duration_s == 2.0
assert not sp2.fit_btn.isEnabled() and "0 s spare" in sp2.timing_label.text()
# Editing the line's text makes the take out of date; nothing is estimated.
project.dialogue = [project.dialogue[0].model_copy(update={"text": "Changed."})]
sp2.refresh()
assert "(out of date)" in sp2.line_list.item(0).text()
assert "need a take" in sp2.timing_label.text() and not sp2.fit_btn.isEnabled()
print("ok")

# Reference views and sheet: views need an unlocked approved design; images
# are copied into the project; the sheet is rendered from the real data.
media = tmp / "media"
cs4 = CharacterStudioPanel(project, media_dir=media)
cs4.char_list.setCurrentRow(0)                       # Maya: approved, locked
assert cs4.view_combo.count() == 11 and not cs4.view_add_btn.isEnabled()
assert "Unlock" in cs4.views_note.text()
from nova_studio.performance import characters as ident
project.put_character(ident.unlock_identity(project.character("maya"), "add views"))
cs4.refresh(select_id="maya")
assert cs4.view_add_btn.isEnabled() and not cs4.view_clear_btn.isEnabled()
side = tmp / "side.png"
q.save(str(side))
assert cs4.set_view_image("side", side)
stored = project.character("maya").approved.views["side"]
assert Path(stored).parent == media / "maya" and Path(stored).is_file()
assert "Side: view-side-" in cs4.view_combo.currentText()
assert cs4.view_clear_btn.isEnabled()
rep = cs4.make_sheet()
assert rep.approved and Path(rep.path).is_file() and "side" in rep.filled
assert Path(rep.path).parent == media / "maya"
assert "views filled" in cs4.views_note.text()
cs4.view_clear_btn.click()
assert "side" not in project.character("maya").approved.views
cs4.char_list.setCurrentRow(1)                       # Leo: nothing approved
assert cs4.view_combo.count() == 0 and "Approve a design first" in cs4.views_note.text()
assert not cs4.make_sheet().approved                 # a DRAFT sheet, never a fake approval
print("ok")
