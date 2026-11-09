"""Media probing via ffprobe (roadmap section 7, milestone 5).

Bad inputs are rejected with useful error messages rather than silently
accepted.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


class FFmpegNotFound(RuntimeError):
    pass


# Environment overrides. Each may point at the binary itself or at the folder
# holding it. NOVA_FFMPEG_DIR covers both tools at once.
ENV_OVERRIDES = {
    "ffmpeg": ("NOVA_FFMPEG", "NOVA_FFMPEG_DIR"),
    "ffprobe": ("NOVA_FFPROBE", "NOVA_FFMPEG_DIR"),
}


def _bundled_dirs() -> list[Path]:
    """Folders where an installed/frozen NOVA ships ffmpeg.exe and ffprobe.exe.

    The installer drops them next to the app executable (or in an 'ffmpeg'
    subfolder). The current working directory is deliberately NOT searched:
    on Windows that would let a stray or planted ffmpeg.exe in whatever folder
    the user happens to be in take precedence.
    """
    dirs: list[Path] = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        dirs += [exe_dir, exe_dir / "ffmpeg", exe_dir / "ffmpeg" / "bin"]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs.append(Path(meipass).resolve())
    return dirs


def _source_tree_dirs() -> list[Path]:
    """Developer convenience: packaging/ffmpeg in a source checkout."""
    if getattr(sys, "frozen", False):
        # In an installed app this path points outside the install folder
        # (e.g. the parent of Program Files\NOVA Studio), which NOVA must not
        # search for executables.
        return []
    root = Path(__file__).resolve().parents[3]
    return [root / "packaging" / "ffmpeg"]


def _exe_names(name: str) -> list[str]:
    return [f"{name}.exe", name] if os.name == "nt" else [name]


def _in_dir(d: Path, name: str) -> list[Path]:
    return [d / n for n in _exe_names(name)]


def _override_candidates(name: str) -> list[Path]:
    out: list[Path] = []
    for var in ENV_OVERRIDES[name]:
        val = os.environ.get(var, "").strip().strip('"')
        if not val:
            continue
        p = Path(val)
        out += _in_dir(p, name) if p.is_dir() else [p]
    return out


def candidate_paths(name: str) -> list[tuple[str, Path]]:
    """Ordered (source, path) candidates: override -> bundled -> PATH -> source tree."""
    cands: list[tuple[str, Path]] = []
    cands += [("override", p) for p in _override_candidates(name)]
    for d in _bundled_dirs():
        cands += [("bundled", p) for p in _in_dir(d, name)]
    on_path = shutil.which(name)
    if on_path:
        cands.append(("PATH", Path(on_path)))
    for d in _source_tree_dirs():
        cands += [("source-tree", p) for p in _in_dir(d, name)]
    return cands


@dataclass
class ToolCheck:
    name: str
    path: str | None = None
    source: str | None = None
    version: str | None = None
    rejected: list[str] | None = None

    @property
    def ok(self) -> bool:
        return self.path is not None


def _verify(path: Path, name: str) -> tuple[bool, str]:
    """Run '<tool> -version' and require a genuine banner.

    This rejects broken stand-ins such as a Chocolatey shim whose target is
    missing (it prints 'Cannot find file ...' instead of a version banner).
    """
    if not path.is_file():
        return False, "not a file"
    try:
        out = subprocess.run(
            [str(path), "-hide_banner", "-version"], capture_output=True,
            text=True, timeout=15, stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if sys.platform == "win32" else 0)
    except Exception as exc:
        return False, f"could not run: {exc}"
    first = (out.stdout or "").strip().splitlines()[:1]
    banner = first[0] if first else ""
    if out.returncode != 0 or not banner.startswith(f"{name} version"):
        detail = (out.stderr or out.stdout or "").strip().splitlines()[:1]
        return False, f"not a working {name} ({detail[0] if detail else 'no version banner'})"
    return True, banner


_cache: dict[str, ToolCheck] = {}


def check_tool(name: str, refresh: bool = False) -> ToolCheck:
    """Find the first candidate that genuinely runs.

    Only a successful lookup is cached. A failure (nothing installed yet, or a
    slow first launch hitting the timeout while antivirus scans the binary) is
    re-checked on the next call, so installing FFmpeg works without a restart.
    """
    if not refresh and name in _cache:
        return _cache[name]
    result = ToolCheck(name=name, rejected=[])
    seen: set[str] = set()
    for source, path in candidate_paths(name):
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        if not path.exists():
            if source == "override":
                result.rejected.append(f"{path} ({source}): does not exist")
            continue
        ok, info = _verify(path, name)
        if ok:
            result.path, result.source, result.version = str(path), source, info
            break
        result.rejected.append(f"{path} ({source}): {info}")
    if result.ok:
        _cache[name] = result
    else:
        _cache.pop(name, None)
    return result


def reset_tool_cache() -> None:
    _cache.clear()


def _require(name: str) -> str:
    chk = check_tool(name)
    if chk.ok:
        return chk.path  # type: ignore[return-value]
    msg = (f"{name} not found. Install a trusted FFmpeg build, set "
           f"{ENV_OVERRIDES[name][0]} to its path, or put it on PATH "
           f"(roadmap section 6C).")
    if chk.rejected:
        msg += " Rejected: " + "; ".join(chk.rejected)
    raise FFmpegNotFound(msg)


def ffprobe_path() -> str:
    return _require("ffprobe")


def ffmpeg_path() -> str:
    return _require("ffmpeg")


@dataclass
class MediaInfo:
    path: str
    ok: bool
    duration_s: float | None = None
    width: int | None = None
    height: int | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    has_video: bool = False
    has_audio: bool = False
    error: str = ""


def probe(path: str | Path) -> MediaInfo:
    p = Path(path)
    if not p.exists():
        return MediaInfo(path=str(p), ok=False, error="File does not exist.")
    try:
        out = subprocess.run(
            [ffprobe_path(), "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(p)],
            capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        )
    except FFmpegNotFound:
        raise
    except Exception as exc:
        return MediaInfo(path=str(p), ok=False, error=f"ffprobe failed: {exc}")

    if out.returncode != 0:
        return MediaInfo(path=str(p), ok=False,
                         error=out.stderr.strip() or "ffprobe returned error.")
    try:
        data = json.loads(out.stdout)
    except Exception as exc:
        return MediaInfo(path=str(p), ok=False, error=f"Bad ffprobe output: {exc}")

    info = MediaInfo(path=str(p), ok=True)
    fmt = data.get("format", {})
    try:
        info.duration_s = float(fmt.get("duration")) if fmt.get("duration") else None
    except (TypeError, ValueError):
        info.duration_s = None

    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and not info.has_video:
            info.has_video = True
            info.video_codec = s.get("codec_name")
            info.width = s.get("width")
            info.height = s.get("height")
        elif s.get("codec_type") == "audio" and not info.has_audio:
            info.has_audio = True
            info.audio_codec = s.get("codec_name")

    if not info.has_video and not info.has_audio:
        info.ok = False
        info.error = "No video or audio streams found; unsupported input."
    return info
