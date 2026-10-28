"""Cross-platform fake Piper CLI for tests (works on Windows + POSIX).

A real-output stand-in for the Piper TTS binary so narration tests run without
installing Piper. It is a Python shim invoked via the current interpreter,
exposed through a launcher named so shutil.which() + subprocess find it on each
OS (piper.bat on Windows, an executable `piper` on POSIX). It writes a genuine
1.5s WAV with ffmpeg — it does not bypass any validation.
"""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

_PIPER_PY = r'''import sys, subprocess
out = None
a = sys.argv[1:]
i = 0
while i < len(a):
    if a[i] == "--output_file":
        out = a[i + 1]; i += 2
    elif a[i] == "--model":
        i += 2
    else:
        i += 1
try:
    sys.stdin.read()
except Exception:
    pass
subprocess.run(["ffmpeg", "-y", "-f", "lavfi",
                "-i", "sine=frequency=220:duration=1.5", "-ar", "22050", out],
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
'''


def install_fake_piper(tmp_path: Path, monkeypatch) -> Path:
    """Put a working 'piper' on PATH (Windows + POSIX). Returns the launcher."""
    from shutil import which
    if not which("ffmpeg"):
        pytest.skip("ffmpeg required for fake piper")
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    shim = bindir / "piper_shim.py"
    shim.write_text(_PIPER_PY)
    if os.name == "nt":
        launcher = bindir / "piper.bat"
        launcher.write_text(f'@echo off\r\n"{sys.executable}" "{shim}" %*\r\n')
    else:
        launcher = bindir / "piper"
        launcher.write_text(
            f'#!/usr/bin/env bash\nexec "{sys.executable}" "{shim}" "$@"\n')
        launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP
                       | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    return launcher
