"""P4.6 photo -> still-video export: real MP4, honest blockers, originals kept."""
import hashlib
import subprocess

import pytest

from nova_studio.phase4.still_video import (ExportConfig, PhotoScene,
                                           StillVideoExporter)
from nova_studio.voice.engine import EngineCapabilities
from nova_studio.voice.narration import VoiceProfile

pytestmark = pytest.mark.export


@pytest.fixture
def fake_piper(tmp_path, monkeypatch):
    from _fake_piper import install_fake_piper  # tests/ is on pythonpath
    install_fake_piper(tmp_path, monkeypatch)
    voice = tmp_path / "v.onnx"
    voice.write_bytes(b"x")
    (tmp_path / "v.onnx.json").write_text("{}")
    return str(voice)


def _profile(voice_path):
    return VoiceProfile(engine_id="piper", voice_path=voice_path,
                        capabilities=EngineCapabilities(speed=True, pause=True,
                                                        pronunciation=True))


def _scenes(photos):
    return [
        PhotoScene(str(photos["good"][0]), caption="One", narration="First."),
        PhotoScene(str(photos["good"][1]), caption="Two", narration="Second."),
        PhotoScene(str(photos["good"][2]), caption="Three", narration="Third."),
    ]


def test_full_export_with_narration_and_subs(photos, tmp_path, fake_piper):
    out = tmp_path / "video.mp4"
    exp = StillVideoExporter()
    r = exp.export(_scenes(photos), tmp_path / "work", str(out),
                   ExportConfig(width=640, height=360, fps=24, preset="ultrafast"),
                   voice_profile=_profile(fake_piper))
    assert r.ok, r.blocker
    assert out.exists()
    names = {s.name: s.ok for s in r.stages}
    assert names == {"narration": True, "subtitles": True, "render": True,
                     "validation": True}
    assert r.has_audio and r.has_subtitles
    # Three streams present.
    streams = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
         "-of", "default=nw=1", str(out)], capture_output=True, text=True).stdout
    assert "video" in streams and "audio" in streams and "subtitle" in streams


def test_originals_preserved(photos, tmp_path, fake_piper):
    before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in photos["good"]]
    exp = StillVideoExporter()
    exp.export(_scenes(photos), tmp_path / "work", str(tmp_path / "v.mp4"),
               ExportConfig(width=640, height=360, fps=24, preset="ultrafast"),
               voice_profile=_profile(fake_piper))
    after = [hashlib.sha256(p.read_bytes()).hexdigest() for p in photos["good"]]
    assert before == after


def test_narration_requested_without_voice_blocks(photos, tmp_path):
    out = tmp_path / "v.mp4"
    exp = StillVideoExporter()
    r = exp.export(_scenes(photos), tmp_path / "work", str(out),
                   ExportConfig(want_narration=True), voice_profile=None)
    assert r.ok is False
    assert "no voice" in r.blocker.lower()
    assert not out.exists()  # never a silent fake video


def test_captions_only_export(photos, tmp_path):
    out = tmp_path / "cap.mp4"
    exp = StillVideoExporter()
    r = exp.export(_scenes(photos), tmp_path / "work", str(out),
                   ExportConfig(width=640, height=360, fps=24, preset="ultrafast",
                                want_narration=False, want_subtitles=True))
    assert r.ok, r.blocker
    assert out.exists()
    # narration stage skipped honestly.
    narr = next(s for s in r.stages if s.name == "narration")
    assert "skipped" in narr.message.lower()


def test_missing_photo_blocks(tmp_path):
    exp = StillVideoExporter()
    r = exp.export([PhotoScene("/does/not/exist.png")], tmp_path / "work",
                   str(tmp_path / "v.mp4"), ExportConfig())
    assert r.ok is False
    assert "not found" in r.blocker.lower()


def test_cancellation_stops_before_render(photos, tmp_path, fake_piper):
    import threading
    cancel = threading.Event()
    cancel.set()  # pre-cancelled
    exp = StillVideoExporter()
    r = exp.export(_scenes(photos), tmp_path / "work", str(tmp_path / "v.mp4"),
                   ExportConfig(width=640, height=360, preset="ultrafast"),
                   voice_profile=_profile(fake_piper), cancel=cancel)
    assert r.ok is False
    assert "cancel" in r.blocker.lower()
