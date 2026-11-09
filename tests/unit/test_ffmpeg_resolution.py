"""FFmpeg lookup: override -> bundled -> PATH, and broken stand-ins rejected."""
import os
import shutil
import sys
from pathlib import Path

import pytest

from nova_studio.core.preflight import check_ffmpeg
from nova_studio.media import probe
from nova_studio.media.probe import FFmpegNotFound, check_tool, reset_tool_cache

EXE = ".exe" if os.name == "nt" else ""


@pytest.fixture(autouse=True)
def real_tools(monkeypatch):
    """Resolve the genuine tools with the caller's environment, then isolate.

    Returns {name: Path or None} so tests can reuse the real binaries however
    they were found (PATH, bundled or NOVA_FFMPEG* override).
    """
    reset_tool_cache()
    real = {n: check_tool(n).path for n in ("ffmpeg", "ffprobe")}
    for var in ("NOVA_FFMPEG", "NOVA_FFPROBE", "NOVA_FFMPEG_DIR"):
        monkeypatch.delenv(var, raising=False)
    reset_tool_cache()
    yield {n: Path(v) if v else None for n, v in real.items()}
    reset_tool_cache()


def _broken_tool(d: Path, name: str) -> Path:
    """An executable that runs but is not FFmpeg (like a dangling choco shim)."""
    d.mkdir(parents=True, exist_ok=True)
    target = d / f"{name}{EXE}"
    if os.name == "nt":
        # A real Windows executable that rejects '-hide_banner -version'.
        shutil.copy(Path(sys.base_prefix) / "python.exe", target)
    else:
        target.write_text("#!/bin/sh\necho \"Cannot find file at '..\\lib\\ffmpeg'\" >&2\nexit 1\n")
        target.chmod(0o755)
    return target


def _isolate(monkeypatch, path_dirs=(), bundled=()):
    monkeypatch.setenv("PATH", os.pathsep.join(str(d) for d in path_dirs))
    monkeypatch.setattr(probe, "_bundled_dirs", lambda: list(bundled))
    monkeypatch.setattr(probe, "_source_tree_dirs", lambda: [])


def test_broken_override_is_rejected_with_reason(tmp_path, monkeypatch):
    bad = _broken_tool(tmp_path / "shim", "ffmpeg")
    _isolate(monkeypatch)
    monkeypatch.setenv("NOVA_FFMPEG", str(bad))
    chk = check_tool("ffmpeg")
    assert not chk.ok
    assert any(str(bad) in r and "override" in r for r in chk.rejected)
    with pytest.raises(FFmpegNotFound, match="Rejected"):
        probe.ffmpeg_path()


def test_missing_override_is_reported(tmp_path, monkeypatch):
    _isolate(monkeypatch)
    monkeypatch.setenv("NOVA_FFMPEG", str(tmp_path / "nope" / f"ffmpeg{EXE}"))
    chk = check_tool("ffmpeg")
    assert not chk.ok
    assert any("does not exist" in r for r in chk.rejected)


def test_nothing_found_explains_how_to_fix(monkeypatch):
    _isolate(monkeypatch)
    with pytest.raises(FFmpegNotFound, match="NOVA_FFPROBE"):
        probe.ffprobe_path()
    diag = check_ffmpeg(refresh=True)
    assert not diag.ok and "ffmpeg" in diag.message and "ffprobe" in diag.message


@pytest.mark.ffmpeg
def test_broken_bundled_copy_falls_through_to_path(tmp_path, monkeypatch, real_tools):
    real_dir = real_tools["ffmpeg"].parent
    bundled = tmp_path / "app"
    _broken_tool(bundled, "ffmpeg")
    _isolate(monkeypatch, path_dirs=[real_dir], bundled=[bundled])
    chk = check_tool("ffmpeg")
    assert chk.ok and chk.source == "PATH"
    assert any("bundled" in r for r in chk.rejected)


@pytest.mark.ffmpeg
def test_order_override_then_bundled_then_path(monkeypatch, real_tools):
    # Point every source at the genuine tools' own folder instead of copying
    # binaries: a copied package-manager shim (e.g. Chocolatey's, as on CI)
    # stops working, which is the very failure this lookup guards against.
    real_dir = real_tools["ffmpeg"].parent

    _isolate(monkeypatch, path_dirs=[real_dir])
    assert check_tool("ffmpeg", refresh=True).source == "PATH"

    _isolate(monkeypatch, path_dirs=[real_dir], bundled=[real_dir])
    assert check_tool("ffmpeg", refresh=True).source == "bundled"

    monkeypatch.setenv("NOVA_FFMPEG_DIR", str(real_dir))
    chk = check_tool("ffmpeg", refresh=True)
    assert chk.source == "override" and chk.version.startswith("ffmpeg version")

    diag = check_ffmpeg(refresh=True)
    assert diag.ok and diag.source == "override"
