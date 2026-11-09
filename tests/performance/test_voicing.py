"""Dialogue voicing: each line in its speaker's own voice, never a stand-in."""
import json
import sys
from pathlib import Path

import pytest

from nova_studio.adapters.base import AdapterResult
from nova_studio.performance.characters import create_character, set_voice
from nova_studio.performance.planner import DialogueLine
from nova_studio.performance.voicing import (
    DialogueVoicer, line_audio_path, write_manifest)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class FakeTTS:
    calls = []

    def __init__(self, voice_path, ok=True):
        self.voice_path, self.ok = voice_path, ok

    def run(self, params):
        FakeTTS.calls.append((Path(self.voice_path).name, params["text"]))
        if not self.ok:
            return AdapterResult(False, message="Piper failed: boom")
        Path(params["out_path"]).write_bytes(b"RIFF" + params["text"].encode())
        return AdapterResult(True, outputs=[params["out_path"]],
                             metrics={"duration_s": 1.2})


@pytest.fixture
def setup(tmp_path):
    voices = tmp_path / "tts"; voices.mkdir()
    (voices / "amy.onnx").write_bytes(b"x"); (voices / "amy.onnx.json").write_text("{}")
    maya = set_voice(create_character("maya", "Maya"), "voice:piper", "amy.onnx")
    leo = create_character("leo", "Leo")
    lines = [DialogueLine(id="l2", order=2, speaker_id="leo", text="Hey."),
             DialogueLine(id="l1", order=1, speaker_id="maya", text="Hi there.")]
    FakeTTS.calls = []
    return voices, [maya, leo], lines, tmp_path / "out"


def test_each_line_uses_its_speakers_voice_and_unvoiced_speakers_are_blocked(setup):
    voices, chars, lines, out = setup
    takes = DialogueVoicer(voices, FakeTTS).voice_all(lines, chars, out)
    assert [t.line_id for t in takes] == ["l1", "l2"]          # script order
    assert takes[0].ok and Path(takes[0].audio_path).read_bytes() == b"RIFFHi there."
    assert takes[0].duration_s == 1.2 and takes[0].voice_id == "amy.onnx"
    assert not takes[1].ok and "no voice assigned" in takes[1].message
    assert not line_audio_path(out, lines[0]).exists()         # no stand-in audio
    assert FakeTTS.calls == [("amy.onnx", "Hi there.")]        # Leo never voiced


def test_missing_voice_cloning_engine_and_unknown_speaker_are_refused(setup):
    voices, chars, lines, out = setup
    v = DialogueVoicer(voices, FakeTTS)
    gone = set_voice(chars[0], "voice:piper", "deleted.onnx")
    assert "not installed" in v.check_line(lines[1], [gone])
    clone = set_voice(chars[0], "voice:xtts_v2", "sample.wav")
    assert "consent" in v.check_line(lines[1], [clone])
    stray = DialogueLine(id="x", order=3, speaker_id="ghost", text="Boo.")
    assert "not a character" in v.check_line(stray, chars)
    empty = DialogueLine(id="e", order=4, speaker_id="maya", text="  ")
    assert v.check_line(empty, chars) == "The line is empty."
    assert FakeTTS.calls == []


def test_failed_retake_keeps_the_previous_good_take(setup):
    voices, chars, lines, out = setup
    DialogueVoicer(voices, FakeTTS).voice_all(lines, chars, out, line_ids=["l1"])
    wav = line_audio_path(out, lines[1])
    before = wav.read_bytes()
    bad = DialogueVoicer(voices, lambda p: FakeTTS(p, ok=False))
    take = bad.voice_line(lines[1], chars, out)
    assert not take.ok and "boom" in take.message
    assert wav.read_bytes() == before
    assert not list(out.glob("*.tmp.wav"))


def test_manifest_merges_per_line(setup):
    voices, chars, lines, out = setup
    v = DialogueVoicer(voices, FakeTTS)
    write_manifest(v.voice_all(lines, chars, out), out)
    write_manifest([v.voice_line(lines[1], chars, out)], out)
    data = json.loads((out / "takes.json").read_text())
    assert set(data) == {"l1", "l2"} and data["l1"]["ok"] and not data["l2"]["ok"]


@pytest.mark.ffmpeg
def test_real_piper_cli_output_is_validated(setup, tmp_path, monkeypatch):
    from _fake_piper import install_fake_piper
    install_fake_piper(tmp_path, monkeypatch)
    voices, chars, lines, out = setup
    take = DialogueVoicer(voices).voice_line(lines[1], chars, out)
    assert take.ok, take.message
    assert take.duration_s and take.duration_s > 1.0
