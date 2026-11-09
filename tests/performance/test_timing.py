"""Shot timing comes only from current, measured takes."""
from pathlib import Path

import pytest

from nova_studio.performance import timing as tm
from nova_studio.performance.characters import create_character, set_voice
from nova_studio.performance.planner import DialogueLine, Shot


@pytest.fixture
def scene(tmp_path):
    maya = set_voice(create_character("maya", "Maya"), "voice:piper", "amy.onnx")
    leo = set_voice(create_character("leo", "Leo"), "voice:piper", "ryan.onnx")
    lines = [DialogueLine(id="a", order=1, speaker_id="maya", text="Hi there."),
             DialogueLine(id="b", order=2, speaker_id="leo", text="Hey.")]
    shot = Shot(id="shot-1", duration_s=4.0, character_ids=["maya", "leo"],
                dialogue_line_ids=["a", "b"])
    wa, wb = tmp_path / "a.wav", tmp_path / "b.wav"
    wa.write_bytes(b"RIFF"); wb.write_bytes(b"RIFF")
    manifest = {
        "a": {"ok": True, "audio_path": str(wa), "text": "Hi there.",
              "voice_id": "amy.onnx", "duration_s": 1.5},
        "b": {"ok": True, "audio_path": str(wb), "text": "Hey.",
              "voice_id": "ryan.onnx", "duration_s": 0.8},
    }
    return [maya, leo], lines, shot, manifest


def test_lines_are_laid_out_from_measured_takes(scene):
    chars, lines, shot, manifest = scene
    t = tm.shot_timing(shot, lines, chars, manifest)
    assert t.complete
    assert [(x.start_s, x.end_s) for x in t.lines] == [(0.4, 1.9), (2.2, 3.0)]
    assert t.needed_s == 3.6 and t.fits and t.suggested_s() == 3.6
    assert "0.4 s spare" in tm.timing_text(t)


def test_too_short_shot_is_reported(scene):
    chars, lines, shot, manifest = scene
    t = tm.shot_timing(shot.model_copy(update={"duration_s": 3.0}), lines,
                       chars, manifest)
    assert t.fits is False and "Too short" in tm.timing_text(t)


def test_edited_line_changed_voice_and_missing_audio_need_a_new_take(scene):
    chars, lines, shot, manifest = scene
    edited = [lines[0].model_copy(update={"text": "Hello there."}), lines[1]]
    t = tm.shot_timing(shot, edited, chars, manifest)
    assert t.lines[0].status == tm.STALE and "edited" in t.lines[0].reason
    assert t.lines[0].start_s is None
    assert not t.complete and t.needed_s is None and t.fits is None
    assert "need a take" in tm.timing_text(t)

    revoiced = [set_voice(chars[0], "voice:piper", "other.onnx"), chars[1]]
    t = tm.shot_timing(shot, lines, revoiced, manifest)
    assert t.lines[0].status == tm.STALE and "voice changed" in t.lines[0].reason

    Path(manifest["b"]["audio_path"]).unlink()
    t = tm.shot_timing(shot, lines, chars, manifest)
    assert t.lines[1].status == tm.NOT_VOICED and "missing" in t.lines[1].reason


def test_no_takes_and_no_dialogue(scene, tmp_path):
    chars, lines, shot, _ = scene
    assert tm.read_manifest(tmp_path / "nowhere") == {}
    (tmp_path / "takes.json").write_text("not json")
    assert tm.read_manifest(tmp_path) == {}
    t = tm.shot_timing(shot, lines, chars, {})
    assert all(x.status == tm.NOT_VOICED for x in t.lines)
    silent = tm.shot_timing(Shot(id="s", duration_s=5.0), lines, chars, {})
    assert silent.needed_s is None and "No dialogue" in tm.timing_text(silent)


def test_changed_approved_pace_makes_the_take_out_of_date(scene):
    chars, lines, shot, manifest = scene
    manifest["a"]["length_scale"] = 1.2
    same = tm.shot_timing(shot, lines, chars, manifest,
                          scale_for=lambda line: 1.2 if line.id == "a" else None)
    assert same.complete
    changed = tm.shot_timing(shot, lines, chars, manifest, scale_for=lambda line: None)
    assert changed.lines[0].status == tm.STALE and "pace" in changed.lines[0].reason
