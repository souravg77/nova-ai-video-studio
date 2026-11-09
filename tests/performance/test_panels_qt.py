"""Real PySide6 widgets, run offscreen in a separate process."""
import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_character_studio_and_shot_plan_widgets():
    script = Path(__file__).with_name("qt_panels_check.py")
    # pytest's pythonpath setting doesn't reach a child process, and CI runs
    # from the source tree without installing the package.
    src = str(Path(__file__).resolve().parents[2] / "src")
    path = os.pathsep.join(p for p in (src, os.environ.get("PYTHONPATH")) if p)
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONPATH": path}
    out = subprocess.run([sys.executable, str(script)], capture_output=True,
                         text=True, env=env, timeout=120)
    if out.returncode == 77:
        pytest.skip("PySide6 is not installed")
    assert out.returncode == 0, out.stdout + out.stderr
    assert out.stdout.strip().endswith("ok")
