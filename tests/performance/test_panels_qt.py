"""Real PySide6 widgets, run offscreen in a separate process."""
import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_character_studio_and_shot_plan_widgets():
    script = Path(__file__).with_name("qt_panels_check.py")
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    out = subprocess.run([sys.executable, str(script)], capture_output=True,
                         text=True, env=env, timeout=120)
    if out.returncode == 77:
        pytest.skip("PySide6 is not installed")
    assert out.returncode == 0, out.stdout + out.stderr
    assert out.stdout.strip().endswith("ok")
