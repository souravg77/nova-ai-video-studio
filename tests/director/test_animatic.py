"""Animatic export: shared timing model, honest frames, no stand-in voices."""
import json
import subprocess

import pytest

from nova_studio.director.animatic import build_animatic
from nova_studio.director.breakdown import apply_breakdown
from nova_studio.director.parser import parse_script
from nova_studio.media.probe import ffmpeg_path, probe
from nova_studio.media.renderer import Renderer
from nova_studio.models.project import Project
from nova_studio.performance.characters import (
    Candidate, CandidateSource, add_candidates, approve_candidate, set_voice)
from nova_studio.performance.voicing import PIPER

SCRIPT = """INT. HALL - NIGHT

ARTHUR
You came back!

ELAINE
I promised I would.
"""


def _tone(path, seconds, freq=440):
    subprocess.run([ffmpeg_path(), "-y", "-f", "lavfi", "-i",
                    f"sine=frequency={freq}:duration={seconds}", "-ar", "22050",
                    str(path)], check=True, capture_output=True)


def _project(tmp_path, approve_elaine=False, placeholder=False):
    p = Project(name="Test")
    apply_breakdown(p, parse_script(SCRIPT), SCRIPT)
    img = tmp_path / "elaine.png"
    subprocess.run([ffmpeg_path(), "-y", "-f", "lavfi", "-i", "color=c=teal:s=320x240:d=1",
                    "-frames:v", "1", str(img)], check=True, capture_output=True)
    for c in list(p.characters):
        c = set_voice(c, PIPER, "voice.onnx")
        if approve_elaine and c.name == "Elaine":
            c = add_candidates(c, [Candidate(id="k", image_path=str(img),
                                             source=CandidateSource.UPLOADED,
                                             is_placeholder=placeholder)])
            c = approve_candidate(c, "k")
        p.put_character(c)
    return p


def _voice(p, audio_dir, lines, seconds=1.5):
    audio_dir.mkdir(parents=True, exist_ok=True)
    data = {}
    for d in lines:
        wav = audio_dir / f"{d.order:04d}.wav"
        _tone(wav, seconds)
        speaker = p.character(d.speaker_id)
        data[d.id] = {"line_id": d.id, "ok": True, "audio_path": str(wav),
                      "duration_s": seconds, "text": d.text,
                      "voice_id": speaker.voice.voice_id}
    (audio_dir / "takes.json").write_text(json.dumps(data), encoding="utf-8")


def _segments(path):
    out = subprocess.run([ffmpeg_path(), "-hide_banner", "-i", str(path), "-af",
                          "silencedetect=noise=-40dB:d=0.2", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    ends = [float(x.split("silence_end: ")[1].split(" ")[0])
            for x in out.splitlines() if "silence_end" in x]
    # Silence that lasts to the end of the file also reports a silence_end
    # (at end of file); that is not the start of a sound.
    total = probe(path).duration_s or 0
    return [e for e in ends if e < total - 0.1]


@pytest.mark.ffmpeg
def test_voiced_lines_play_where_the_timing_model_puts_them(tmp_path):
    p = _project(tmp_path)
    _voice(p, tmp_path / "dialogue", p.dialogue)
    rep = build_animatic(p, Renderer(), tmp_path / "dialogue", tmp_path / "a.mp4",
                         width=320, height=180, fps=12, preset="ultrafast")
    assert rep.ok, rep.message
    assert rep.voiced_lines == 2 and rep.unvoiced == []
    info = probe(rep.output_path)
    assert info.has_audio and info.has_video
    # establishing 3.0 s, then each dialogue shot lengthened to fit its take:
    # lead-in 0.4 + 1.5 s line + tail 0.6 = 2.5 s.
    assert [round(b, 1) for _, _, b in rep.lengthened] == [2.5, 2.5]
    starts = _segments(rep.output_path)        # end of each silence = a line starts
    assert starts[0] == pytest.approx(3.0 + 0.4, abs=0.15)
    assert starts[1] == pytest.approx(3.0 + 2.5 + 0.4, abs=0.15)


@pytest.mark.ffmpeg
def test_unvoiced_and_stale_lines_are_text_only_and_reported(tmp_path):
    p = _project(tmp_path)
    _voice(p, tmp_path / "dialogue", p.dialogue[:1])
    p.dialogue[0].text = "You came back, at last!"          # edited after voicing
    rep = build_animatic(p, Renderer(), tmp_path / "dialogue", tmp_path / "b.mp4",
                         width=320, height=180, fps=12, preset="ultrafast")
    assert rep.ok and rep.voiced_lines == 0
    assert [(u.speaker, u.status) for u in rep.unvoiced] == [
        ("Arthur", "out of date"), ("Elaine", "not voiced")]
    assert "shown as text only (no audio)" in rep.summary()
    assert _segments(rep.output_path) == []                 # no stand-in voice anywhere


@pytest.mark.ffmpeg
def test_only_real_approved_designs_are_used_as_frames(tmp_path):
    p = _project(tmp_path, approve_elaine=True)
    rep = build_animatic(p, Renderer(), None, tmp_path / "c.mp4",
                         width=320, height=180, fps=12, preset="ultrafast")
    assert (rep.image_frames, rep.title_cards) == (1, 2)    # Elaine's line only
    p = _project(tmp_path, approve_elaine=True, placeholder=True)
    rep = build_animatic(p, Renderer(), None, tmp_path / "d.mp4",
                         width=320, height=180, fps=12, preset="ultrafast")
    assert (rep.image_frames, rep.title_cards) == (0, 3)    # placeholders never used


def test_no_shots_is_refused(tmp_path):
    rep = build_animatic(Project(), Renderer(ffmpeg="unused"), None, tmp_path / "x.mp4")
    assert not rep.ok and "Break down a script" in rep.message
