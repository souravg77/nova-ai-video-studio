"""Gemini Omni Flash adapter: opt-in only, key never leaks, no fake takes.

All HTTP is faked; these tests never touch the network.
"""
import base64
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from nova_studio.adapters.gemini_omni import (
    API_BASE, CAPABILITIES, GeminiOmniEngine, ImageInput, OmniError, OmniRequest)
from nova_studio.performance.engines import EngineRegistry
from nova_studio.performance.planner import (
    DialogueLine, EngineSelection, PlanContext, Route, Shot, plan_shot)
from nova_studio.security.offline_mode import NetworkPolicy, NetworkPolicyError

KEY = "AIza-test-secret-key"


@dataclass
class FakeInfo:
    ok: bool = True
    has_video: bool = True
    has_audio: bool = True
    duration_s: float = 6.0
    width: int = 1280
    height: int = 720
    error: str = ""


class FakeHTTP:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append((method, url, dict(headers), body))
        return self.responses.pop(0)


def engine(http, enabled=True, key=KEY, probe=lambda p: FakeInfo()):
    return GeminiOmniEngine(api_key_provider=lambda: key,
                            cloud_enabled=lambda: enabled, transport=http,
                            sleep=lambda s: None, media_probe=probe)


def inline_response(data=b"fake-mp4"):
    return 200, json.dumps({"id": "v1_abc", "status": "completed", "steps": [
        {"type": "model_output", "content": [
            {"type": "video", "mime_type": "video/mp4",
             "data": base64.b64encode(data).decode()}]}]}).encode()


def test_off_by_default_and_without_key_it_is_unavailable_and_sends_nothing(tmp_path):
    http = FakeHTTP([])
    off = engine(http, enabled=False)
    assert not off.status().available and "switched off" in off.status().reason
    with pytest.raises(OmniError, match="switched off"):
        off.generate(OmniRequest("a cat"), tmp_path / "t.mp4")
    nokey = engine(http, key="")
    assert not nokey.status().available and "API key" in nokey.status().reason
    assert http.calls == []


def test_network_policy_blocks_cloud_unless_enabled():
    with pytest.raises(NetworkPolicyError):
        NetworkPolicy().guard_network("cloud_generation")
    with pytest.raises(NetworkPolicyError):
        NetworkPolicy().enter_download_mode().guard_network("cloud_generation")
    NetworkPolicy().enable_cloud_generation().guard_network("cloud_generation")


def test_key_only_in_header_never_in_url_or_errors(tmp_path):
    http = FakeHTTP([(403, json.dumps({"error": {"message": "API key not valid"}}).encode())])
    with pytest.raises(OmniError) as err:
        engine(http).generate(OmniRequest("a cat"), tmp_path / "t.mp4")
    method, url, headers, body = http.calls[0]
    assert method == "POST" and url == f"{API_BASE}/interactions"
    assert headers["x-goog-api-key"] == KEY
    assert KEY not in url and KEY not in body.decode() and KEY not in str(err.value)
    assert "HTTP 403" in str(err.value) and "API key not valid" in str(err.value)


def test_request_body_matches_documented_shape(tmp_path):
    first = tmp_path / "a.png"; first.write_bytes(b"\x89PNG")
    ref = tmp_path / "maya.jpg"; ref.write_bytes(b"\xff\xd8")
    body = engine(FakeHTTP([])).build_body(OmniRequest(
        "Maya smiles.", aspect_ratio="9:16", duration_s=6,
        images=[ImageInput(ref, "reference"), ImageInput(first, "first_frame")]))
    assert body["model"] == "gemini-omni-1.1-flash"
    assert body["response_format"] == {"type": "video", "delivery": "uri",
                                       "aspect_ratio": "9:16", "resolution": "720p"}
    kinds = [(i["type"], i.get("mime_type")) for i in body["input"]]
    assert kinds == [("image", "image/png"), ("image", "image/jpeg"), ("text", None)]
    assert "about 6 seconds" in body["input"][-1]["text"]


@pytest.mark.parametrize("req,msg", [
    (OmniRequest("x", aspect_ratio="1:1"), "Aspect ratio"),
    (OmniRequest("x", duration_s=12), "3-10 s"),
    (OmniRequest("   "), "no prompt"),
])
def test_invalid_requests_are_refused_before_sending(req, msg):
    with pytest.raises(OmniError, match=msg):
        engine(FakeHTTP([])).build_body(req)


def test_inline_video_is_saved_and_verified(tmp_path):
    take = engine(FakeHTTP([inline_response(b"bytes")])).generate(
        OmniRequest("a cat", duration_s=6), tmp_path / "take.mp4")
    assert take.path.read_bytes() == b"bytes"
    assert take.interaction_id == "v1_abc" and take.watermark == "SynthID"
    assert take.has_audio and take.requested_duration_s == 6


def test_uri_delivery_polls_until_active_then_downloads_with_header(tmp_path):
    uri = f"{API_BASE}/files/abc123:download?alt=media"
    http = FakeHTTP([
        (200, json.dumps({"id": "v1_x", "steps": [{"type": "model_output", "content": [
            {"type": "video", "mime_type": "video/mp4", "uri": uri}]}]}).encode()),
        (200, json.dumps({"state": "PROCESSING"}).encode()),
        (200, json.dumps({"state": "ACTIVE"}).encode()),
        (200, b"mp4-bytes"),
    ])
    take = engine(http).generate(OmniRequest("a cat"), tmp_path / "t.mp4")
    urls = [c[1] for c in http.calls]
    assert urls[1:] == [f"{API_BASE}/files/abc123", f"{API_BASE}/files/abc123",
                        f"{API_BASE}/files/abc123:download?alt=media"]
    assert all(KEY not in u for u in urls)
    assert all(c[2]["x-goog-api-key"] == KEY for c in http.calls)
    assert take.path.read_bytes() == b"mp4-bytes"


def test_failed_file_and_missing_video_are_errors_not_takes(tmp_path):
    uri = f"{API_BASE}/files/f1:download?alt=media"
    http = FakeHTTP([
        (200, json.dumps({"steps": [{"content": [{"type": "video", "uri": uri}]}]}).encode()),
        (200, json.dumps({"state": "FAILED", "error": {"message": "safety"}}).encode()),
    ])
    with pytest.raises(OmniError, match="failed"):
        engine(http).generate(OmniRequest("a cat"), tmp_path / "t.mp4")
    http = FakeHTTP([(200, json.dumps({"status": "failed", "steps": []}).encode())])
    with pytest.raises(OmniError, match="no video"):
        engine(http).generate(OmniRequest("a cat"), tmp_path / "t2.mp4")
    assert not (tmp_path / "t.mp4").exists() and not (tmp_path / "t2.mp4").exists()


def test_unplayable_download_is_deleted_not_kept(tmp_path):
    bad = engine(FakeHTTP([inline_response(b"junk")]),
                 probe=lambda p: FakeInfo(ok=False, has_video=False, error="bad data"))
    with pytest.raises(OmniError, match="not a playable video"):
        bad.generate(OmniRequest("a cat"), tmp_path / "t.mp4")
    assert not (tmp_path / "t.mp4").exists()


@pytest.mark.ffmpeg
def test_real_mp4_passes_real_ffprobe_verification(tmp_path):
    from nova_studio.media.probe import ffmpeg_path
    src = tmp_path / "src.mp4"
    subprocess.run([ffmpeg_path(), "-y", "-f", "lavfi", "-i", "testsrc=s=320x240:d=1",
                    "-f", "lavfi", "-i", "sine=d=1", "-shortest", "-pix_fmt", "yuv420p",
                    str(src)], capture_output=True, check=True)
    eng = GeminiOmniEngine(lambda: KEY, lambda: True,
                           transport=FakeHTTP([inline_response(src.read_bytes())]))
    take = eng.generate(OmniRequest("a test pattern"), tmp_path / "out.mp4")
    assert take.has_audio and take.width == 320 and take.duration_s > 0.5


def test_planner_uses_omni_for_single_english_speaker_and_flags_cloud():
    eng = engine(FakeHTTP([]))
    reg = EngineRegistry([eng.spec()])
    shot = Shot(id="s1", duration_s=6, dialogue_line_ids=["l1"])
    ctx = PlanContext(characters=[], dialogue=[DialogueLine(id="l1", order=1,
                      speaker_id="narr", text="Hello.")],
                      selection=EngineSelection(video="gemini-omni-flash"))
    plan = plan_shot(shot, ctx, reg)
    assert plan.route == Route.NATIVE_AV and plan.can_proceed
    assert any(l.code == "cloud_engine" for l in plan.limitations)
    # Switched off: blocked with the reason, never silently replaced.
    off = engine(FakeHTTP([]), enabled=False)
    plan = plan_shot(shot, ctx, EngineRegistry([off.spec()]))
    assert not plan.can_proceed
    assert any("switched off" in l.message for l in plan.blockers)


def test_declared_capabilities_stay_conservative():
    assert CAPABILITIES.languages == ("en",)
    assert not CAPABILITIES.multi_speaker_in_one_shot
    assert CAPABILITIES.max_duration_s == 10 and CAPABILITIES.is_cloud
