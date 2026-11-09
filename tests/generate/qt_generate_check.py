"""Drives the real Generate panel offscreen (run by test_generate_qt.py).

Exit code 77 means PySide6 is not installed. HTTP is faked; no network.
"""
import base64
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import importlib.util

if importlib.util.find_spec("PySide6") is None:
    sys.exit(77)
from PySide6.QtWidgets import QApplication, QMessageBox

from nova_studio.adapters.gemini_omni import GeminiOmniEngine
from nova_studio.media.probe import check_tool, ffmpeg_path
from nova_studio.models.project import Project
from nova_studio.performance import characters as ident
from nova_studio.performance.planner import Shot
from nova_studio.ui.generate_panel import GeneratePanel

app = QApplication.instance() or QApplication([])
warnings = []
QMessageBox.warning = staticmethod(lambda *a, **k: warnings.append(a[2]))
tmp = Path(tempfile.mkdtemp())
have_ffmpeg = check_tool("ffmpeg").ok and check_tool("ffprobe").ok


@dataclass
class Info:
    ok: bool = True
    has_video: bool = True
    has_audio: bool = True
    duration_s: float = 2.0
    width: int = 160
    height: int = 90
    error: str = ""


clip_bytes = b"mp4"
if have_ffmpeg:
    real = tmp / "real.mp4"
    subprocess.run([ffmpeg_path(), "-y", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc=size=160x90:rate=24:duration=2", str(real)], check=True)
    clip_bytes = real.read_bytes()

calls = []


def http(method, url, headers, body, timeout):
    calls.append(json.loads(body) if body else None)
    return 200, json.dumps({"id": f"v1_{len(calls)}", "output_video": {
        "data": base64.b64encode(clip_bytes).decode()}}).encode()


enabled = {"on": False}
eng = GeminiOmniEngine(api_key_provider=lambda: "k", cloud_enabled=lambda: enabled["on"],
                       transport=http, sleep=lambda s: None, media_probe=lambda p: Info())
img = tmp / "maya.png"; img.write_bytes(b"\x89PNG")
maya = ident.create_character("maya", "Maya")
maya = ident.add_candidates(maya, [ident.Candidate(
    id="c1", image_path=str(img), source=ident.CandidateSource.UPLOADED)])
maya = ident.lock_identity(ident.approve_candidate(maya, "c1"))
project = Project(name="t"); project.put_character(maya)
project.shots = [Shot(id="shot-1", duration_s=6.0, character_ids=["maya"]),
                 Shot(id="shot-2", duration_s=4.0)]
asked = []
answer = {"yes": True}
changes = []
gp = GeneratePanel(project, engine=eng, generations_dir=tmp / "gen",
                   on_changed=lambda: changes.append(1),
                   confirm=lambda text: (asked.append(text), answer["yes"])[1])

# Cloud off: blocked, with the reason, and nothing is sent.
gp.prompt_edit.setPlainText("Maya opens the door.")
assert not gp.generate_btn.isEnabled()
assert "switched off" in gp.blocker_label.text()
enabled["on"] = True
gp.refresh()
assert gp.prompt_edit.toPlainText() == "Maya opens the door."   # kept per shot
assert gp.generate_btn.isEnabled(), gp.blocker_label.text()
assert gp.dur_spin.value() == 6.0
# Saying no sends nothing.
answer["yes"] = False
assert not gp.generate() and calls == [] and "Not sent" in gp.progress_label.text()
# Two versions from the approved character.
answer["yes"] = True
gp.mode_combo.setCurrentIndex(gp.mode_combo.findData("characters"))
gp.out_spin.setValue(2)
assert "2 requests" in gp.usage_label.text()
assert gp.generate()
gp.wait()
assert len(calls) == 2 and calls[0]["input"][0]["type"] == "image"
assert "about 6 seconds" in calls[0]["input"][-1]["text"]
assert "2 of 2 version(s) generated" in gp.progress_label.text()
assert gp.version_list.count() == 2 and asked and "billed" in asked[-1]
gp.version_list.setCurrentRow(0)
assert gp.choose_btn.isEnabled(); gp.choose_btn.click()
assert gp.version_list.item(0).text().startswith("CHOSEN")
assert "clip chosen" in gp.shot_list.item(0).text()
from nova_studio.generate.versions import chosen_clip
assert chosen_clip(tmp / "gen", "shot-1") is not None
# Frames mode needs a start frame; picking one copies it into the project.
gp.mode_combo.setCurrentIndex(gp.mode_combo.findData("frames"))
assert not gp.generate_btn.isEnabled() and "start frame" in gp.blocker_label.text()
start = tmp / "start.png"; start.write_bytes(b"\x89PNG")
assert gp.set_frame("start_frame", start)
s1 = project.shots[0]
assert Path(s1.start_frame).parent == tmp / "gen" / "frames" and gp.generate_btn.isEnabled()
assert changes
# A frame of the chosen version becomes the next shot's start frame.
if have_ffmpeg:
    gp.version_list.setCurrentRow(0)
    gp.frame_at.setValue(1.0)
    assert gp.next_start_btn.isEnabled()
    gp.next_start_btn.click()
    s2 = project.shots[1]
    assert s2.start_frame and Path(s2.start_frame).is_file(), warnings
    assert "start frame of shot-2" in gp.version_detail.text()
# The last shot has no next shot.
gp.shot_list.setCurrentRow(1)
assert gp.version_list.count() == 0 and not gp.next_start_btn.isEnabled()
# No engine at all: says so.
none = GeneratePanel(project, engine=None, generations_dir=tmp / "gen")
assert not none.generate_btn.isEnabled() and "No video engine" in none.blocker_label.text()

# A local engine next to the cloud one: picked by the user, never asked to
# confirm a send (nothing leaves the PC), and limited by its own capabilities.
from nova_studio.performance.engines import (EngineCapabilities, EngineSpec,
                                             EngineStatus, Role)
from nova_studio.adapters.gemini_omni import OmniTake


class LocalEngine:
    resolutions = ("320p",)
    model = "local-test"
    runs = []

    def spec(self):
        return EngineSpec(id="local-test", name="Local preview (test)",
                          roles=frozenset({Role.VIDEO}),
                          capabilities=EngineCapabilities(
                              video_generation=True, min_duration_s=1.0,
                              max_duration_s=2.0, aspect_ratios=("16:9",)),
                          status_fn=lambda: EngineStatus(True))

    def status(self):
        return EngineStatus(True)

    def generate(self, req, out_path, on_progress=None):
        LocalEngine.runs.append(req.prompt)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(clip_bytes)
        return OmniTake(path=out_path, interaction_id="", duration_s=1.0,
                        has_audio=False, width=512, height=320,
                        requested_duration_s=req.duration_s, model="local-test")


asked.clear()
two = GeneratePanel(project, generations_dir=tmp / "gen",
                    engines=[eng, LocalEngine()],
                    confirm=lambda text: (asked.append(text), True)[1])
assert two.engine_combo.count() == 2 and two.engine_combo.isEnabled()
two.engine_combo.setCurrentIndex(1)
assert [two.res_combo.itemText(i) for i in range(two.res_combo.count())] == ["320p"]
assert two.dur_spin.maximum() == 2.0 and two.dur_spin.value() == 2.0
two.prompt_edit.setPlainText("A quick preview.")
two.mode_combo.setCurrentIndex(two.mode_combo.findData("characters"))
assert not two.generate_btn.isEnabled() and "character references" in two.blocker_label.text()
two.mode_combo.setCurrentIndex(two.mode_combo.findData("text"))
assert "Nothing is sent" in two.usage_label.text()
assert two.generate(); two.wait()
assert LocalEngine.runs == ["A quick preview."] and asked == []
assert "local-test" in two.version_detail.text() and "SynthID" not in two.version_detail.text()
print("ok")
