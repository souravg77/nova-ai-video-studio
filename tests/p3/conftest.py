"""P3 fixtures: a cross-platform fake Piper CLI that writes real WAVs."""
from __future__ import annotations

from pathlib import Path

import pytest

from _fake_piper import install_fake_piper  # tests/ is on pythonpath


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
    return install_fake_piper(tmp_path, monkeypatch)
