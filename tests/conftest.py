"""Shared fixtures: a temp workspace and generated media assets."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from nova_studio.config import AppConfig, Paths


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path / "ws"


@pytest.fixture
def app_config(workspace: Path) -> AppConfig:
    return AppConfig(paths=Paths.create(workspace)).ensure()


def _ffmpeg() -> str | None:
    # Use the app's own lookup (override -> bundled -> PATH) so tests see
    # exactly the FFmpeg NOVA would use, and never a broken shim.
    from nova_studio.media.probe import check_tool
    return check_tool("ffmpeg").path


def _ffmpeg_ready() -> bool:
    from nova_studio.media.probe import check_tool
    return check_tool("ffmpeg").ok and check_tool("ffprobe").ok


def pytest_collection_modifyitems(config, items):
    """Skip @pytest.mark.ffmpeg tests cleanly when FFmpeg/FFprobe are absent."""
    if _ffmpeg_ready():
        return
    skip = pytest.mark.skip(reason="ffmpeg/ffprobe not available")
    for item in items:
        if "ffmpeg" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def assets(tmp_path: Path):
    """Generate small test assets with ffmpeg. Skips if ffmpeg is absent."""
    ff = _ffmpeg()
    if not ff:
        pytest.skip("ffmpeg not available")
    d = tmp_path / "assets"
    d.mkdir()
    img = d / "img.png"
    clip = d / "clip.mp4"
    narr = d / "narr.wav"
    subprocess.run([ff, "-y", "-f", "lavfi", "-i", "color=c=navy:s=640x360:d=1",
                    "-frames:v", "1", str(img)], check=True, capture_output=True)
    subprocess.run([ff, "-y", "-f", "lavfi", "-i", "testsrc=s=640x360:r=24:d=2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)],
                   check=True, capture_output=True)
    subprocess.run([ff, "-y", "-f", "lavfi", "-i", "sine=frequency=330:duration=3",
                    str(narr)], check=True, capture_output=True)
    return {"img": img, "clip": clip, "narr": narr, "dir": d}
