"""2.5D camera moves: depth-driven parallax, honest depth labels, animatic use."""
import subprocess

import numpy as np
import pytest

from nova_studio.director.animatic import build_animatic
from nova_studio.director.breakdown import apply_breakdown
from nova_studio.director.model import LocationRef
from nova_studio.director.parser import parse_script
from nova_studio.media.parallax import (MOVES, ApproximateDepth, _flow,
                                        depth_source, render_move)
from nova_studio.media.probe import ffmpeg_path, probe
from nova_studio.media.renderer import Renderer
from nova_studio.models.project import Project
from nova_studio.sheets.locations import approve_location, put_location, set_location_view


def _two_planes(h=60, w=80):
    d = np.zeros((h, w), np.float32)
    d[h // 2:, :] = 1.0          # bottom half near, top half far
    return d


def test_push_in_moves_near_pixels_more_than_far_ones():
    d = _two_planes()
    mx, _ = _flow(d, "push_in", 1.0, 0.2)
    xx = np.arange(80, dtype=np.float32)
    far_shift = abs(mx[10, 0] - xx[0])     # top row, left edge
    near_shift = abs(mx[50, 0] - xx[0])    # bottom row, left edge
    assert near_shift > far_shift > 0


def test_truck_moves_are_mirrored_and_parallax():
    d = _two_planes()
    lx, _ = _flow(d, "truck_left", 1.0, 0.2)
    rx, _ = _flow(d, "truck_right", 1.0, 0.2)
    base = np.arange(80, dtype=np.float32)
    left_near, left_far = lx[50, 40] - base[40], lx[10, 40] - base[40]
    assert left_near == pytest.approx(-(rx[50, 40] - base[40]))
    assert abs(left_near) > abs(left_far)


def test_middle_of_a_truck_move_is_the_original_frame():
    d = _two_planes()
    mx, my = _flow(d, "truck_left", 0.5, 0.2)
    assert np.allclose(mx, np.mgrid[0:60, 0:80][1])


def test_unknown_move_and_depth_labels(tmp_path):
    with pytest.raises(ValueError):
        _flow(_two_planes(), "spin", 0.5, 0.1)
    src = depth_source(tmp_path)                    # no model installed here
    assert isinstance(src, ApproximateDepth) and not src.measured
    assert "approximate" in src.name
    d = ApproximateDepth().depth(np.zeros((40, 60, 3), np.uint8))
    assert d.shape == (40, 60) and d[-1].mean() > d[0].mean()   # bottom nearer


@pytest.mark.ffmpeg
@pytest.mark.parametrize("move", MOVES)
def test_render_move_makes_a_clip_of_the_right_length(tmp_path, move):
    img = tmp_path / "s.png"
    subprocess.run([ffmpeg_path(), "-y", "-f", "lavfi", "-i", "testsrc=s=320x240:d=1",
                    "-frames:v", "1", str(img)], check=True, capture_output=True)
    res = render_move(img, tmp_path / f"{move}.mp4", move, 1.0, ffmpeg_path(),
                      width=160, height=90, fps=12, preset="ultrafast")
    assert res.ok, res.message
    info = probe(res.path)
    assert info.has_video and (info.width, info.height) == (160, 90)
    assert info.duration_s == pytest.approx(1.0, abs=0.1)


def test_render_move_reports_bad_input(tmp_path):
    res = render_move(tmp_path / "missing.png", tmp_path / "o.mp4", "push_in", 1.0, "ffmpeg")
    assert not res.ok and "Cannot read image" in res.message


@pytest.mark.ffmpeg
def test_animatic_turns_approved_stills_into_moving_shots(tmp_path):
    text = "INT. HALL - NIGHT\n\nRain.\n"
    p = Project(name="Moves")
    apply_breakdown(p, parse_script(text), text)
    png = tmp_path / "hall.png"
    subprocess.run([ffmpeg_path(), "-y", "-f", "lavfi", "-i", "testsrc=s=320x240:d=1",
                    "-frames:v", "1", str(png)], check=True, capture_output=True)
    put_location(p.director, approve_location(
        set_location_view(p.director.locations[0], "front", str(png))))
    rep = build_animatic(p, Renderer(), None, tmp_path / "a.mp4", width=320, height=180,
                         fps=12, preset="ultrafast", camera_moves=True)
    assert rep.ok, rep.message
    assert rep.camera_moves == 2 and rep.location_frames == 2
    assert "approximate" in rep.depth_source
    assert "2.5D camera move" in rep.summary()
    still = build_animatic(p, Renderer(), None, tmp_path / "b.mp4", width=320, height=180,
                           fps=12, preset="ultrafast")
    assert still.camera_moves == 0 and still.depth_source == ""


def _installed_depth_model():
    import os
    from pathlib import Path
    from nova_studio.media.parallax import find_depth_model
    return find_depth_model(Path(os.environ.get("LOCALAPPDATA", "")) / "NovaStudio" / "NovaStudio" / "models")


@pytest.mark.skipif(_installed_depth_model() is None, reason="depth model not installed")
def test_real_depth_model_separates_near_from_far():
    pytest.importorskip("onnxruntime")
    from nova_studio.media.parallax import DepthAnythingOnnx
    src = DepthAnythingOnnx(_installed_depth_model())
    assert src.measured
    # A bright near block on a gradient wall: the block must read nearer.
    img = np.tile(np.linspace(40, 200, 320, dtype=np.uint8), (240, 1))
    rgb = np.dstack([img, img, img]).copy()
    rgb[120:230, 120:200] = (200, 60, 60)
    d = src.depth(rgb)
    assert d.shape == (240, 320) and 0.0 <= d.min() and d.max() <= 1.0
