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
def test_order_override_then_bundled_then_path(tmp_path, monkeypatch, real_tools):
    real_ff = real_tools["ffmpeg"]
    # Use the real tools' own folder as the "bundled" dir rather than copying
    # them: on CI the tool on PATH is a Chocolatey shim, which only works from
    # its install location, so a copy would (correctly) be rejected.
    real_dir = real_ff.parent
    _isolate(monkeypatch, path_dirs=[real_dir], bundled=[real_dir])

    assert check_tool("ffmpeg", refresh=True).source == "bundled"

    monkeypatch.setenv("NOVA_FFMPEG_DIR", str(real_ff.parent))
    chk = check_tool("ffmpeg", refresh=True)
    assert chk.source == "override" and chk.version.startswith("ffmpeg version")

    diag = check_ffmpeg(refresh=True)
    assert diag.ok and diag.source == "override"


@pytest.mark.ffmpeg
def test_failed_lookup_is_not_cached(monkeypatch, real_tools):
    """Installing FFmpeg while NOVA is open must work without a restart."""
    _isolate(monkeypatch)
    assert not check_tool("ffmpeg").ok
    monkeypatch.setenv("PATH", str(real_tools["ffmpeg"].parent))
    chk = check_tool("ffmpeg")  # no refresh=True: a failure must not stick
    assert chk.ok and chk.source == "PATH"


def test_frozen_app_does_not_search_outside_install_dir(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert probe._source_tree_dirs() == []


def test_app_starts_without_ffmpeg_and_render_reports_it(tmp_path, monkeypatch):
    """No FFmpeg must not stop NOVA starting (Setup & diagnostics explains it)."""
    from nova_studio import config
    from nova_studio.core.studio import Studio
    from nova_studio.media.renderer import Renderer

    _isolate(monkeypatch)
    r = Renderer()
    with pytest.raises(FFmpegNotFound):
        _ = r.ffmpeg
    assert Renderer(ffmpeg="C:/custom/ffmpeg.exe").ffmpeg == "C:/custom/ffmpeg.exe"

    cfg = config.AppConfig(paths=config.Paths.create(tmp_path / "ws")).ensure()
    studio = Studio(cfg)
    try:
        assert "ffmpeg" not in studio.report.backends_available
    finally:
        studio.shutdown()
