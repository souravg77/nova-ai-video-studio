"""Extend: measured, never assumed; the original version is untouched."""
import subprocess
from pathlib import Path

import pytest

from nova_studio.adapters.gemini_omni import (ENGINE_ID, GeminiOmniEngine, OmniError,
                                              OmniRequest, OmniTake)
from nova_studio.generate.extend import can_extend, extend_version
from nova_studio.generate.versions import Version, VersionStore


def clip(path: Path, secs: float, freq=440):
    from nova_studio.media.probe import ffmpeg_path
    subprocess.run([ffmpeg_path(), "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"testsrc=size=320x180:rate=24:duration={secs}", "-f", "lavfi",
                    "-i", f"sine=frequency={freq}:duration={secs}", "-shortest",
                    str(path)], check=True)
    return path


class FakeOmni:
    model = "gemini-omni-1.1-flash"

    def __init__(self, make, fail=None):
        self.make, self.fail, self.reqs = make, fail, []

    def generate(self, req, out_path, on_progress=None):
        self.reqs.append(req)
        if self.fail:
            raise OmniError(self.fail)
        secs = self.make(out_path)
        return OmniTake(path=out_path, interaction_id="v1_ext", duration_s=secs,
                        has_audio=True, width=320, height=180, requested_duration_s=None)


def parent(tmp_path, store, secs=4.0):
    v = Version(id="ver-p", shot_id="s1", mode="text", prompt="A walk.", ok=True,
                path=str(clip(tmp_path / "p.mp4", secs)), engine_id=ENGINE_ID,
                interaction_id="v1_parent", duration_s=secs, has_audio=True,
                width=320, height=180, aspect_ratio="16:9", resolution="720p")
    store.add(v)
    return v


def test_request_body_continues_the_earlier_interaction():
    eng = GeminiOmniEngine(api_key_provider=lambda: "k", cloud_enabled=lambda: True)
    body = eng.build_body(OmniRequest("She keeps walking.", duration_s=6,
                                      previous_interaction_id="v1_abc"))
    assert body["previous_interaction_id"] == "v1_abc"
    assert body["generation_config"] == {"video_config": {"task": "extend"}}
    assert body["input"].startswith("She keeps walking.")


def test_only_playable_gemini_versions_can_be_extended(tmp_path):
    assert "Pick a version" in can_extend(None)
    local = Version(id="x", shot_id="s", mode="text", prompt="p", ok=True,
                    path=str(tmp_path / "missing.mp4"), engine_id="local")
    assert "playable" in can_extend(local)
    (tmp_path / "f.mp4").write_bytes(b"x")
    local.path = str(tmp_path / "f.mp4")
    assert "Gemini" in can_extend(local)


@pytest.mark.ffmpeg
def test_continuation_only_is_joined_after_the_original(tmp_path):
    store = VersionStore(tmp_path / "gen")
    p = parent(tmp_path, store)
    eng = FakeOmni(lambda out: (clip(out, 3, freq=660), 3.0)[1])
    v = extend_version(eng, p, "She keeps walking.", 3, store)
    assert v.ok, v.message
    assert eng.reqs[0].previous_interaction_id == "v1_parent"
    assert abs(v.duration_s - 7.0) < 0.3 and "joined" in v.message
    assert v.parent_id == "ver-p" and v.mode == "extend" and v.interaction_id == "v1_ext"
    assert Path(p.path).is_file()                 # original untouched
    assert len(store.versions("s1")) == 2


@pytest.mark.ffmpeg
def test_whole_clip_is_kept_as_returned(tmp_path):
    store = VersionStore(tmp_path / "gen")
    p = parent(tmp_path, store)
    v = extend_version(FakeOmni(lambda out: (clip(out, 8), 8.0)[1]), p, "More.", 4, store)
    assert v.ok and abs(v.duration_s - 8.0) < 0.3 and "whole clip" in v.message


def test_a_failed_extend_is_recorded_with_its_reason(tmp_path):
    store = VersionStore(tmp_path / "gen")
    f = tmp_path / "p.mp4"; f.write_bytes(b"x")
    p = Version(id="ver-p", shot_id="s1", mode="text", prompt="p", ok=True, path=str(f),
                engine_id=ENGINE_ID, interaction_id="v1_old", duration_s=4.0)
    v = extend_version(FakeOmni(None, fail="Interaction not found"), p, "More.", 4, store)
    assert not v.ok and "not found" in v.message and not v.path
    with pytest.raises(ValueError):
        extend_version(FakeOmni(None), p, "  ", 4, store)
