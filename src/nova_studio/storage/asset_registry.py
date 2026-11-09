"""Asset registry: import files into a project with probing + validation.

User-uploaded originals are never modified in place; the registry records
references and probed metadata (roadmap section 7, milestone 5).
"""
from __future__ import annotations

import re
from pathlib import Path

from ..media.probe import probe
from ..models.project import Asset, AssetKind, Project

_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"}
_VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
_AUDIO_EXT = {".wav", ".mp3", ".aac", ".m4a", ".flac", ".ogg"}
_SUB_EXT = {".srt", ".vtt", ".ass"}


_RESERVED = {"CON", "PRN", "AUX", "NUL",
             *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def safe_filename(name: str | None, fallback: str = "output", max_len: int = 80) -> str:
    """A file name Windows will accept, derived from a user-typed title.

    A project called "My film: part 1?" used to render to "My film" (0 bytes)
    with the video hidden in an NTFS alternate data stream, because ':' is a
    stream separator and '?' is not allowed. Forbidden characters become '-',
    reserved device names are avoided and trailing dots/spaces removed.
    """
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", (name or "").strip())
    s = re.sub(r"-{2,}", "-", s).strip(" .-")[:max_len].rstrip(" .")
    if not s:
        return fallback
    if s.split(".")[0].upper() in _RESERVED:
        s = f"{s}_"
    return s


def classify(path: str | Path) -> AssetKind | None:
    ext = Path(path).suffix.lower()
    if ext in _IMAGE_EXT:
        return AssetKind.IMAGE
    if ext in _VIDEO_EXT:
        return AssetKind.VIDEO
    if ext in _AUDIO_EXT:
        return AssetKind.AUDIO
    if ext in _SUB_EXT:
        return AssetKind.SUBTITLE
    return None


def import_asset(project: Project, path: str | Path) -> Asset:
    """Import and validate a media file. Returns an Asset (valid flag set).

    Raises ValueError with a useful message for bad inputs.
    """
    p = Path(path)
    kind = classify(p)
    if kind is None:
        raise ValueError(
            f"Unsupported file type '{p.suffix}'. Supported: images "
            f"{sorted(_IMAGE_EXT)}, video {sorted(_VIDEO_EXT)}, audio "
            f"{sorted(_AUDIO_EXT)}, subtitles {sorted(_SUB_EXT)}.")
    if not p.exists():
        raise ValueError(f"File does not exist: {p}")

    asset = Asset(kind=kind, path=str(p.resolve()))

    if kind in (AssetKind.VIDEO, AssetKind.AUDIO, AssetKind.IMAGE):
        info = probe(p)
        if not info.ok:
            asset.valid = False
            asset.note = f"Rejected: {info.error}"
            raise ValueError(f"'{p.name}' could not be read: {info.error}")
        asset.valid = True
        asset.duration_s = info.duration_s
        asset.width = info.width
        asset.height = info.height
        asset.codec = info.video_codec or info.audio_codec
    else:
        asset.valid = p.stat().st_size > 0

    project.add_asset(asset)
    return asset
