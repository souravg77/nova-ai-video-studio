"""Subtitle alignment from real audio + validation flags."""
import subprocess
from pathlib import Path

import pytest

from nova_studio.media.probe import ffmpeg_path
from nova_studio.voice.subtitles import (SceneAudio, align_subtitles, to_srt,
                                        validate_scene_audio, write_srt)

pytestmark = pytest.mark.export  # needs ffmpeg for real durations


def _wav(ff, path, seconds, freq=330):
    subprocess.run([ff, "-y", "-f", "lavfi",
                    "-i", f"sine=frequency={freq}:duration={seconds}",
                    "-ar", "22050", str(path)], check=True, capture_output=True)


def test_srt_timing_matches_audio(tmp_path):
    ff = ffmpeg_path()
    a0 = tmp_path / "a0.wav"; _wav(ff, a0, 3)
    a1 = tmp_path / "a1.wav"; _wav(ff, a1, 2)
    scenes = [SceneAudio(0, "First scene narration here.", str(a0)),
              SceneAudio(1, "Second.", str(a1))]
    res = align_subtitles(scenes)
    assert res.ok  # no errors
    assert abs(res.total_duration_s - 5.0) < 0.3
    # Cues cover 0..5s roughly in order.
    assert res.cues[0].start_s == 0.0
    assert res.cues[-1].end_s <= 5.1
    srt = to_srt(res.cues)
    assert "-->" in srt and srt.strip().startswith("1")


def test_missing_audio_flagged_as_error(tmp_path):
    empty = tmp_path / "empty.wav"
    empty.write_bytes(b"")
    scenes = [SceneAudio(0, "Has no audio.", str(empty))]
    res = align_subtitles(scenes)
    assert res.ok is False
    assert any(f.kind == "missing" and f.level == "error" for f in res.flags)


def test_write_srt_file(tmp_path):
    ff = ffmpeg_path()
    a0 = tmp_path / "a0.wav"; _wav(ff, a0, 2)
    res = align_subtitles([SceneAudio(0, "Hello world.", str(a0))])
    out = write_srt(res.cues, tmp_path / "subs.srt")
    assert out.exists()
    assert "-->" in out.read_text()
