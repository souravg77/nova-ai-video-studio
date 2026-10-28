"""P3 fixtures: a fake Piper CLI that writes real WAVs (as in P2)."""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest


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
    from shutil import which
    if not which("ffmpeg"):
        pytest.skip("ffmpeg required for fake piper")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    piper = bindir / "piper"
    piper.write_text(
        "#!/usr/bin/env bash\n"
        "set -e\n"
        "OUT=''\n"
        "while [ $# -gt 0 ]; do\n"
        "  case \"$1\" in\n"
        "    --output_file) OUT=\"$2\"; shift 2;;\n"
        "    --model) shift 2;;\n"
        "    *) shift;;\n"
        "  esac\n"
        "done\n"
        "cat >/dev/null\n"
        "ffmpeg -y -f lavfi -i sine=frequency=220:duration=1.5 "
        "-ar 22050 \"$OUT\" >/dev/null 2>&1\n"
    )
    piper.chmod(piper.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    return piper
