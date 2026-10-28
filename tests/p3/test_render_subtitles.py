"""Renderer muxes an SRT into the MP4 as a soft subtitle track."""
import subprocess

import pytest

from nova_studio.media.probe import ffmpeg_path, ffprobe_path, probe
from nova_studio.media.renderer import Renderer, RenderSpec, SceneSpec

pytestmark = pytest.mark.export


def test_render_with_soft_subtitles(assets, tmp_path):
    # Build a tiny SRT.
    srt = tmp_path / "s.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:02,000\nHello there\n")
    out = tmp_path / "subbed.mp4"
    spec = RenderSpec(
        width=640, height=360, fps=24, preset="ultrafast",
        scenes=[SceneSpec(kind="image", source=str(assets["img"]),
                          duration_s=2, caption="x", motion="kenburns")],
        narration_path=str(assets["narr"]),
        subtitle_srt_path=str(srt),
        output_path=str(out))
    result = Renderer().render(spec)
    assert result.ok, result.message
    # Probe for a subtitle stream.
    probe_out = subprocess.run(
        [ffprobe_path(), "-v", "error",
         "-select_streams", "s", "-show_entries", "stream=codec_name",
         "-of", "default=nw=1", str(out)],
        capture_output=True, text=True)
    assert "mov_text" in probe_out.stdout


def test_render_without_subtitles_unaffected(assets, tmp_path):
    out = tmp_path / "plain.mp4"
    spec = RenderSpec(
        width=640, height=360, fps=24, preset="ultrafast",
        scenes=[SceneSpec(kind="image", source=str(assets["img"]),
                          duration_s=2, caption="x")],
        output_path=str(out))
    result = Renderer().render(spec)
    assert result.ok
    assert probe(out).has_video
