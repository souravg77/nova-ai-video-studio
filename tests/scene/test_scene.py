"""Scene builder: chosen clips in order, trims, gaps shown honestly, a real export."""
import subprocess
from pathlib import Path

import pytest

from nova_studio.generate.versions import Version, VersionStore
from nova_studio.models.project import Project
from nova_studio.performance.planner import Shot
from nova_studio.scene import sequence as sq
from nova_studio.scene.export import export_scene


def clip(path: Path, secs: float, size="320x180", audio=True):
    from nova_studio.media.probe import ffmpeg_path
    args = [ffmpeg_path(), "-y", "-v", "error", "-f", "lavfi", "-i",
            f"testsrc=size={size}:rate=24:duration={secs}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={secs}", "-shortest"]
    subprocess.run(args + [str(path)], check=True)
    return path


def add(store, shot_id, path, dur, audio=True, vid=None):
    v = Version(id=vid or f"ver-{shot_id}", shot_id=shot_id, mode="text", prompt="p",
                ok=True, path=str(path), duration_s=dur, has_audio=audio)
    store.add(v)
    return v


@pytest.fixture
def setup(tmp_path):
    p = Project(name="t")
    p.shots = [Shot(id="s1", duration_s=4.0), Shot(id="s2", duration_s=3.0),
               Shot(id="s3", duration_s=2.0)]
    gen = tmp_path / "gen"
    return p, VersionStore(gen), sq.SceneStore(gen), tmp_path


def test_order_trim_and_gaps(setup):
    p, vs, scene, tmp = setup
    f = tmp / "a.mp4"; f.write_bytes(b"x")
    v = add(vs, "s1", f, 6.0); vs.choose("s1", v.id)
    start = tmp / "start.png"; start.write_bytes(b"png")
    p.shots = [p.shots[0], p.shots[1].model_copy(update={"start_frame": str(start)}), p.shots[2]]
    cuts = sq.resolve(p, vs, scene)
    assert [(c.shot_id, c.kind) for c in cuts] == [("s1", "clip"), ("s2", "still"), ("s3", "card")]
    assert cuts[0].duration_s == 6.0 and cuts[1].duration_s == 3.0
    assert "No clip chosen" in cuts[2].note
    scene.set_trim("s1", v, 1.0, 4.5)
    assert sq.resolve(p, vs, scene)[0].duration_s == 3.5
    for bad in ((4.0, 4.2), (-1, 3), (2, 7)):
        with pytest.raises(ValueError):
            scene.set_trim("s1", v, *bad)
    # Choosing another version resets the trim.
    v2 = add(vs, "s1", f, 5.0, vid="ver-other"); vs.choose("s1", v2.id)
    assert sq.resolve(p, vs, scene)[0].out_s == 5.0
    # Reorder; deleted shots drop out, new ones are appended.
    assert scene.move(p, "s3", -2) == ["s3", "s1", "s2"]
    p.shots = [s for s in p.shots if s.id != "s1"] + [Shot(id="s4", duration_s=1.0)]
    assert scene.order(p) == ["s3", "s2", "s4"]
    assert sq.total_s(sq.resolve(p, vs, scene)) == 6.0


def test_nothing_to_export_without_any_clip(setup):
    p, vs, scene, tmp = setup
    r = export_scene(sq.resolve(p, vs, scene), tmp / "out.mp4")
    assert not r.ok and "No shot has a chosen clip" in r.message
    assert not (tmp / "out.mp4").exists()


@pytest.mark.ffmpeg
def test_export_keeps_clip_sound_and_fills_gaps_with_silence(setup):
    from nova_studio.media.probe import probe
    p, vs, scene, tmp = setup
    a = add(vs, "s1", clip(tmp / "a.mp4", 3), 3.0)
    b = add(vs, "s2", clip(tmp / "b.mp4", 2, size="180x320", audio=False), 2.0, audio=False)
    vs.choose("s1", a.id); vs.choose("s2", b.id)
    scene.set_trim("s1", a, 0.5, 2.5)
    out = tmp / "scene.mp4"
    r = export_scene(sq.resolve(p, vs, scene), out, width=320, height=180)
    assert r.ok, r.message
    info = probe(out)
    assert info.has_video and info.has_audio and (info.width, info.height) == (320, 180)
    assert abs(info.duration_s - 6.0) < 0.3          # 2.0 + 2.0 + 2.0 (card)
    assert r.gaps == ["s3"] and "s3" in r.message
    assert not list(tmp.glob("*.part.mp4"))


@pytest.mark.ffmpeg
def test_export_trusts_the_file_not_the_record_for_sound(setup):
    p, vs, scene, tmp = setup
    silent = clip(tmp / "s.mp4", 2, audio=False)
    v = add(vs, "s1", silent, 2.0, audio=True)     # record wrongly says sound
    vs.choose("s1", v.id)
    r = export_scene(sq.resolve(p, vs, scene)[:1], tmp / "o.mp4", width=320, height=180)
    assert r.ok, r.message
