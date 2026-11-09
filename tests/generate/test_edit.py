"""Edit by prompt: Google's edit task; measured result; original untouched."""
from pathlib import Path

import pytest

from nova_studio.adapters.gemini_omni import GeminiOmniEngine, OmniError, OmniRequest
from nova_studio.generate.edit import can_edit, edit_version
from nova_studio.generate.versions import Version, VersionStore

from test_extend import FakeOmni, clip, parent


def eng():
    return GeminiOmniEngine(api_key_provider=lambda: "k", cloud_enabled=lambda: True)


def test_request_body_asks_for_the_edit_task():
    body = eng().build_body(OmniRequest("Make it night.", previous_interaction_id="v1_a",
                                        task="edit"))
    assert body["previous_interaction_id"] == "v1_a"
    assert body["generation_config"] == {"video_config": {"task": "edit"}}
    assert body["input"] == "Make it night."          # no duration hint added


def test_edit_requests_are_checked():
    with pytest.raises(OmniError, match="earlier Gemini clip"):
        eng().build_body(OmniRequest("x", task="edit"))
    with pytest.raises(OmniError, match="length"):
        eng().build_body(OmniRequest("x", duration_s=5, previous_interaction_id="v1",
                                     task="edit"))
    with pytest.raises(OmniError, match="Unknown task"):
        eng().build_body(OmniRequest("x", previous_interaction_id="v1", task="upscale"))


def test_only_playable_gemini_versions_can_be_edited(tmp_path):
    assert "Pick a version" in can_edit(None)
    f = tmp_path / "f.mp4"; f.write_bytes(b"x")
    local = Version(id="x", shot_id="s", mode="text", prompt="p", ok=True,
                    path=str(f), engine_id="ltx-local")
    assert "Gemini" in can_edit(local)


@pytest.mark.ffmpeg
def test_edited_clip_becomes_a_new_linked_version(tmp_path):
    store = VersionStore(tmp_path / "gen")
    p = parent(tmp_path, store)
    fake = FakeOmni(lambda out: (clip(out, 4, freq=660), 4.0)[1])
    v = edit_version(fake, p, "Make it night.", store)
    assert v.ok, v.message
    assert fake.reqs[0].task == "edit" and fake.reqs[0].duration_s is None
    assert fake.reqs[0].previous_interaction_id == "v1_parent"
    assert v.mode == "edit" and v.parent_id == "ver-p" and abs(v.duration_s - 4.0) < 0.3
    assert "Edited by prompt" in v.message and "original was" not in v.message
    assert Path(p.path).is_file() and Path(v.path).is_file() and v.path != p.path


@pytest.mark.ffmpeg
def test_a_bad_or_failed_edit_is_recorded_not_faked(tmp_path):
    store = VersionStore(tmp_path / "gen")
    p = parent(tmp_path, store)
    bad = edit_version(FakeOmni(lambda out: (out.write_bytes(b"junk"), 4.0)[1]),
                       p, "Night.", store)
    assert not bad.ok and "validation" in bad.message and not bad.path
    failed = edit_version(FakeOmni(None, fail="Interaction expired"), p, "Night.", store)
    assert not failed.ok and "expired" in failed.message
    with pytest.raises(ValueError):
        edit_version(FakeOmni(None), p, " ", store)
