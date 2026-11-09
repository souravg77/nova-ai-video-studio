"""Local LTX-Video engine: honest status, Gemini-compatible interface."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from nova_studio.adapters import ltx_local
from nova_studio.adapters.gemini_omni import ImageInput, OmniError, OmniRequest
from nova_studio.adapters.ltx_local import (CAPABILITIES, LtxLocalEngine,
                                            engine_for_studio, find_weights, frames_for)


def _weights(tmp_path, cls="LTXPipeline"):
    d = tmp_path / "models" / "video" / "ltx"
    (d / "transformer").mkdir(parents=True)
    (d / "model_index.json").write_text(json.dumps({"_class_name": cls}), encoding="utf-8")
    return d


class FakePipe:
    def __init__(self):
        self.calls = []

    def generate(self, prompt, **kw):
        self.calls.append((prompt, kw))
        n, h, w = kw["num_frames"], kw["height"], kw["width"]
        frames = np.zeros((1, n, h, w, 3), np.uint8)
        frames[..., 0] = np.linspace(0, 255, n, dtype=np.uint8)[None, :, None, None]
        return SimpleNamespace(video=SimpleNamespace(data=frames))


def _engine(tmp_path, enabled=True, runtime=True, probe=None, ffmpeg=None):
    pipe = FakePipe()
    eng = LtxLocalEngine(_weights(tmp_path), preview_enabled=lambda: enabled,
                         runtime_ok=lambda: runtime, pipeline_factory=lambda d, dev: pipe,
                         probe=probe, ffmpeg=ffmpeg)
    return eng, pipe


def test_frame_counts_follow_ltx_rules():
    assert frames_for(None) == 25 and frames_for(1.0) == 25
    assert frames_for(0.1) == 9 and frames_for(10) == 49
    assert all((frames_for(s) - 1) % 8 == 0 for s in (0.3, 0.7, 1.3, 1.7, 2.0))


def test_capabilities_are_honest():
    assert not CAPABILITIES.is_cloud and not CAPABILITIES.native_audio
    assert CAPABILITIES.max_reference_images == 0 and not CAPABILITIES.start_end_frames
    assert CAPABILITIES.max_duration_s < 2.1 and set(CAPABILITIES.aspect_ratios) == {"16:9", "9:16"}
    assert LtxLocalEngine.resolutions == ("288p",) and LtxLocalEngine.model


def test_weights_are_found_only_for_an_ltx_pipeline(tmp_path):
    assert find_weights(tmp_path / "models") is None
    _weights(tmp_path, cls="StableDiffusionPipeline")
    assert find_weights(tmp_path / "models") is None
    d = tmp_path / "other"
    _weights(d)
    assert find_weights(d / "models").name == "ltx"


def test_status_says_why_it_cannot_run(tmp_path):
    eng, _ = _engine(tmp_path, enabled=False)
    st = eng.status()
    assert not st.available and "Setup & diagnostics" in st.reason and "non-commercial" in st.reason
    eng, _ = _engine(tmp_path / "b", runtime=False)
    assert "OpenVINO GenAI runtime" in eng.status().reason
    eng = LtxLocalEngine(None, preview_enabled=lambda: True, runtime_ok=lambda: True)
    assert "No converted LTX-Video weights" in eng.status().reason
    assert eng.spec().status().available is False


@pytest.mark.parametrize("req, msg", [
    (OmniRequest(prompt=" "), "no prompt"),
    (OmniRequest(prompt="x", images=[ImageInput(Path("a.png"), "first_frame")]), "text only"),
    (OmniRequest(prompt="x", aspect_ratio="1:1"), "Aspect ratio"),
    (OmniRequest(prompt="x", resolution="720p"), "288p only"),
])
def test_requests_it_cannot_honour_are_refused(tmp_path, req, msg):
    eng, pipe = _engine(tmp_path)
    with pytest.raises(OmniError, match=msg):
        eng.generate(req, tmp_path / "o.mp4")
    assert pipe.calls == []


def test_disabled_engine_never_runs(tmp_path):
    eng, pipe = _engine(tmp_path, enabled=False)
    with pytest.raises(OmniError, match="Switch on"):
        eng.generate(OmniRequest(prompt="a cat", resolution="288p"), tmp_path / "o.mp4")
    assert pipe.calls == []


@pytest.mark.ffmpeg
def test_generate_encodes_and_verifies_a_take(tmp_path):
    eng, pipe = _engine(tmp_path)
    seen = []
    take = eng.generate(OmniRequest(prompt="a lighthouse at dawn", aspect_ratio="9:16",
                                    resolution="288p", duration_s=0.7),
                        tmp_path / "take.mp4", on_progress=seen.append)
    kw = pipe.calls[0][1]
    assert (kw["width"], kw["height"], kw["num_frames"]) == (288, 512, 17)
    assert (take.width, take.height, take.has_audio) == (288, 512, False)
    assert take.interaction_id == "" and take.duration_s == pytest.approx(17 / 24, abs=0.05)
    assert take.model == LtxLocalEngine.model and seen


def test_a_take_that_is_not_video_is_rejected_and_removed(tmp_path):
    bad = SimpleNamespace(ok=False, has_video=False, error="no video stream")
    eng, _ = _engine(tmp_path, probe=lambda p: bad)
    eng._encode = lambda frames, out: out.write_bytes(b"junk")
    out = tmp_path / "t.mp4"
    with pytest.raises(OmniError, match="not a playable video"):
        eng.generate(OmniRequest(prompt="x", resolution="288p"), out)
    assert not out.exists()


def test_engine_for_studio_returns_none_without_runtime_or_weights(tmp_path, monkeypatch):
    studio = SimpleNamespace(config=SimpleNamespace(paths=SimpleNamespace(
        models=tmp_path / "models", workspace=tmp_path)))
    monkeypatch.setattr(ltx_local, "runtime_available", lambda: False)
    assert engine_for_studio(studio) is None
    monkeypatch.setattr(ltx_local, "runtime_available", lambda: True)
    assert engine_for_studio(studio) is None            # no weights
    _weights(tmp_path)
    eng = engine_for_studio(studio)
    assert eng is not None and not eng.status().available   # off until switched on


@pytest.mark.skipif(not os.environ.get("NOVA_SLOW_TESTS"),
                    reason="real local generation takes ~2 minutes; set NOVA_SLOW_TESTS=1")
def test_real_local_generation():
    models = Path(os.environ.get("LOCALAPPDATA", "")) / "NovaStudio" / "NovaStudio" / "models"
    weights = find_weights(models)
    if weights is None or not ltx_local.runtime_available():
        pytest.skip("LTX-Video runtime or weights not installed")
    eng = LtxLocalEngine(weights, preview_enabled=lambda: True)
    take = eng.generate(OmniRequest(prompt="waves on a beach", resolution="288p"),
                        Path(os.environ["TEMP"]) / "nova_ltx_real.mp4")
    assert (take.width, take.height) == (512, 288)
