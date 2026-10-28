"""P2 fixtures: real-output shims for llama.cpp and Piper.

We cannot ship Qwen2.5/Piper weights in CI, so these fixtures install:
  * a stub `llama_cpp` module whose create_chat_completion returns a real JSON
    scene array, and
  * a fake `piper` CLI on PATH that writes a genuine WAV via ffmpeg.

The point is to exercise the REAL pipeline code paths — parsing, per-scene
narration, file validation, FFmpeg muxing — exactly as they run with real
weights. The shims produce valid files; they do not bypass validation.
"""
from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path

import pytest


@pytest.fixture
def fake_gguf(tmp_path: Path) -> Path:
    """A placeholder .gguf file so the resolver/adapter sees a model present."""
    d = tmp_path / "models" / "script"
    d.mkdir(parents=True)
    f = d / "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf"
    f.write_bytes(b"GGUF\x00fake-weights-for-test")
    return f


@pytest.fixture
def stub_llama(monkeypatch):
    """Install a stub `llama_cpp` that returns real, parseable scene JSON."""
    mod = types.ModuleType("llama_cpp")

    class Llama:
        def __init__(self, *a, **k):
            self.model_path = k.get("model_path")

        def create_chat_completion(self, messages, max_tokens=900,
                                   temperature=0.7, **k):
            # Derive scene count from the user prompt for realism.
            n = 3
            for m in messages:
                if m["role"] == "user" and "exactly" in m["content"]:
                    import re
                    mm = re.search(r"exactly (\d+)", m["content"])
                    if mm:
                        n = int(mm.group(1))
            scenes = [
                {"title": f"Scene {i+1}",
                 "narration": f"This is the narration for scene {i+1}.",
                 "caption": f"Scene {i+1}"}
                for i in range(n)
            ]
            import json
            return {"choices": [{"message": {"content": json.dumps(scenes)}}]}

    mod.Llama = Llama
    monkeypatch.setitem(sys.modules, "llama_cpp", mod)
    return mod


@pytest.fixture
def fake_piper_voice(tmp_path: Path) -> Path:
    d = tmp_path / "models" / "tts"
    d.mkdir(parents=True)
    onnx = d / "en_US-test-medium.onnx"
    onnx.write_bytes(b"ONNX-fake-voice")
    (d / "en_US-test-medium.onnx.json").write_text('{"sample_rate": 22050}')
    return onnx


@pytest.fixture
def fake_piper_cli(tmp_path: Path, monkeypatch):
    """A cross-platform fake `piper` on PATH that writes a real WAV via ffmpeg."""
    from _fake_piper import install_fake_piper  # tests/ is on pythonpath
    return install_fake_piper(tmp_path, monkeypatch)
