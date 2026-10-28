"""Real FFmpeg render tests (the P1 core deliverable)."""
import pytest

from nova_studio.media.renderer import Renderer, RenderSpec, SceneSpec
from nova_studio.media.probe import probe
from nova_studio.media.quality_checks import validate_output

pytestmark = pytest.mark.export


def test_render_still_plus_clip_with_audio(assets, tmp_path):
    out = tmp_path / "out.mp4"
    spec = RenderSpec(
        width=640, height=360, fps=24, preset="ultrafast",
        scenes=[
            SceneSpec(kind="image", source=str(assets["img"]), duration_s=2,
                      caption="Scene one", motion="kenburns"),
            SceneSpec(kind="video", source=str(assets["clip"]), duration_s=2,
                      caption="Scene two"),
        ],
        narration_path=str(assets["narr"]),
        output_path=str(out),
    )
    result = Renderer().render(spec)
    assert result.ok, result.message
    # Duration must be ~4s (2 + 2), proving the zoompan frame-count fix.
    assert 3.5 <= result.duration_s <= 4.6, f"bad duration {result.duration_s}"
    report = validate_output(str(out), expect_audio=True)
    assert report.ok, report.reasons
    assert report.has_audio


def test_kenburns_duration_exact(assets, tmp_path):
    out = tmp_path / "seg.mp4"
    r = Renderer()
    spec = RenderSpec(width=640, height=360, fps=24, preset="ultrafast",
                      scenes=[SceneSpec(kind="image", source=str(assets["img"]),
                                        duration_s=3, motion="kenburns")])
    r._render_segment(spec.scenes[0], spec, out)
    info = probe(out)
    assert info.ok
    assert abs((info.duration_s or 0) - 3.0) < 0.3


def test_render_no_scenes_fails_cleanly(tmp_path):
    out = tmp_path / "x.mp4"
    result = Renderer().render(RenderSpec(scenes=[], output_path=str(out)))
    assert result.ok is False
    assert "No scenes" in result.message
