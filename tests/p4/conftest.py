"""P4 fixtures: generate test photos of various quality."""
from __future__ import annotations

import subprocess
from pathlib import Path
from shutil import which

import pytest


def _png(path: Path, color: str, size: str):
    ff = which("ffmpeg")
    if not ff:
        pytest.skip("ffmpeg required")
    subprocess.run([ff, "-y", "-f", "lavfi",
                    "-i", f"color=c={color}:s={size}:d=1",
                    "-frames:v", "1", str(path)],
                   check=True, capture_output=True)


@pytest.fixture
def photos(tmp_path: Path):
    d = tmp_path / "photos"
    d.mkdir()
    good1 = d / "good1.png"; _png(good1, "gray", "512x512")
    good2 = d / "good2.png"; _png(good2, "0x808080", "640x480")
    good3 = d / "good3.png"; _png(good3, "0x909090", "512x512")
    tiny = d / "tiny.png"; _png(tiny, "white", "100x100")
    dark = d / "dark.png"; _png(dark, "0x050505", "512x512")
    return {"good": [good1, good2, good3], "tiny": tiny, "dark": dark, "dir": d}
