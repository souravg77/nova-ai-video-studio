"""Asset registry: import files into a project with probing + validation.

User-uploaded originals are never modified in place; the registry records
references and probed metadata (roadmap section 7, milestone 5).
"""
from __future__ import annotations

from pathlib import Path

from ..media.probe import probe
from ..models.project import Asset, AssetKind, Project

_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"}
_VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
_AUDIO_EXT = {".wav", ".mp3", ".aac", ".m4a", ".flac", ".ogg"}
_SUB_EXT = {".srt", ".vtt", ".ass"}


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
