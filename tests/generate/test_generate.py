"""Generate: requests built only from approved material, every version kept,
nothing faked. All HTTP is faked; these tests never touch the network."""
import base64
import json
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

import pytest

from nova_studio.adapters.gemini_omni import GeminiOmniEngine, OmniError
from nova_studio.generate import request as gr
from nova_studio.generate.frames import save_frame
from nova_studio.generate.runner import run_generation
from nova_studio.generate.versions import VersionStore, chosen_clip
from nova_studio.models.project import Project
from nova_studio.performance import characters as ident
from nova_studio.performance.planner import Shot


@dataclass
class Info:
    ok: bool = True
    has_video: bool = True
    has_audio: bool = True
    duration_s: float = 6.0
    width: int = 1280
    height: int = 720
    error: str = ""


class HTTP:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append((method, url, json.loads(body) if body else None))
        return self.responses.pop(0)


def ok_resp(n):
    return 200, json.dumps({"id": f"v1_{n}", "status": "completed", "output_video": {
        "data": base64.b64encode(b"mp4-%d" % n).decode()}}).encode()


def engine(http, enabled=True):
    return GeminiOmniEngine(api_key_provider=lambda: "k", cloud_enabled=lambda: enabled,
                            transport=http, sleep=lambda s: None,
                            media_probe=lambda p: Info())


@pytest.fixture
def project(tmp_path):
    img = tmp_path / "maya.png"; img.write_bytes(b"\x89PNG fake")
    maya = ident.create_character("maya", "Maya")
    maya = ident.add_candidates(maya, [ident.Candidate(
        id="c1", image_path=str(img), source=ident.CandidateSource.UPLOADED)])
    maya = ident.lock_identity(ident.approve_candidate(maya, "c1"))
    leo = ident.create_character("leo", "Leo")
    p = Project(name="t")
    p.put_character(maya); p.put_character(leo)
    p.shots = [Shot(id="shot-1", duration_s=5.0, character_ids=["maya"]),
               Shot(id="shot-2", duration_s=4.0, character_ids=["maya", "leo"])]
    return p


def test_character_mode_sends_only_approved_designs(project):
    ok = gr.prepare(gr.GenerateSpec("shot-1", "characters", "Maya waves."), project)
    assert ok.ok and [i.role for i in ok.request.images] == ["reference"]
    blocked = gr.prepare(gr.GenerateSpec("shot-2", "characters", "Both wave."), project)
    assert not blocked.ok and any("Leo has no approved design" in b for b in blocked.blockers)


def test_frames_mode_needs_a_start_frame_and_text_needs_a_prompt(project, tmp_path):
    assert "Set the shot's start frame first." in gr.prepare(
        gr.GenerateSpec("shot-1", "frames", "Go."), project).blockers
    assert "Describe the shot first." in gr.prepare(
        gr.GenerateSpec("shot-1", "text", "  "), project).blockers
    start = tmp_path / "start.jpg"; start.write_bytes(b"jpg")
    project.shots = [project.shots[0].model_copy(update={"start_frame": str(start)}),
                     project.shots[1]]
    prep = gr.prepare(gr.GenerateSpec("shot-1", "frames", "She turns."), project)
    assert prep.ok and prep.request.images[0].role == "first_frame"
    assert prep.inputs == [str(start)]


def test_usage_is_stated_per_request():
    text = gr.usage_text(gr.GenerateSpec("s", "text", "x", outputs=3, duration_s=6))
    assert "3 requests" in text and "about 18 s" in text and "billed" in text


def test_every_version_is_kept_and_failures_are_recorded(project, tmp_path):
    http = HTTP([ok_resp(1), (500, b'{"error":{"message":"overloaded"}}'), ok_resp(3)])
    store = VersionStore(tmp_path / "gen")
    spec = gr.GenerateSpec("shot-1", "text", "A door opens.", outputs=3, duration_s=6)
    vs = run_generation(engine(http), spec, project, store)
    assert [v.ok for v in vs] == [True, False, True]
    assert "overloaded" in vs[1].message and not vs[1].path
    assert Path(vs[0].path).read_bytes() == b"mp4-1"
    assert len(http.calls) == 3                     # one request per version
    assert [v.id for v in store.versions("shot-1")] == [v.id for v in vs]
    # Choosing: only a playable version, and only for its own shot.
    with pytest.raises(ValueError):
        store.choose("shot-1", vs[1].id)
    with pytest.raises(ValueError):
        store.choose("shot-2", vs[0].id)
    store.choose("shot-1", vs[2].id)
    assert chosen_clip(tmp_path / "gen", "shot-1") == Path(vs[2].path)
    Path(vs[2].path).unlink()                        # file gone: nothing chosen
    assert chosen_clip(tmp_path / "gen", "shot-1") is None


def test_cloud_off_or_blocked_request_sends_nothing(project, tmp_path):
    http = HTTP([])
    store = VersionStore(tmp_path / "gen")
    vs = run_generation(engine(http, enabled=False),
                        gr.GenerateSpec("shot-1", "text", "x"), project, store)
    assert not vs[0].ok and "switched off" in vs[0].message and http.calls == []
    with pytest.raises(ValueError, match="Leo"):
        run_generation(engine(http), gr.GenerateSpec("shot-2", "characters", "x"),
                       project, store)
    assert http.calls == []


def test_stop_skips_the_remaining_versions(project, tmp_path):
    http = HTTP([ok_resp(1)])
    cancel = threading.Event()
    store = VersionStore(tmp_path / "gen")
    eng = engine(http)
    real = eng.generate

    def gen_then_stop(*a, **k):
        t = real(*a, **k); cancel.set(); return t
    eng.generate = gen_then_stop
    vs = run_generation(eng, gr.GenerateSpec("shot-1", "text", "x", outputs=3),
                        project, store, cancel=cancel)
    assert len(vs) == 1 and len(http.calls) == 1


@pytest.mark.ffmpeg
def test_save_frame_reads_a_real_frame(tmp_path):
    from nova_studio.media.probe import ffmpeg_path
    clip = tmp_path / "c.mp4"
    subprocess.run([ffmpeg_path(), "-y", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc=size=160x90:rate=24:duration=2", str(clip)], check=True)
    out = save_frame(clip, 1.0, tmp_path / "f" / "frame.png")
    assert out.is_file() and out.stat().st_size > 0
    with pytest.raises(ValueError):
        save_frame(tmp_path / "missing.mp4", 0, tmp_path / "x.png")
