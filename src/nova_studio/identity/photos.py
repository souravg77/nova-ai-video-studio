"""Three-photo intake + validation (Phase 4, P4.1 / P4.2).

Imports exactly three reference photos and validates each: format, dimensions,
file integrity, and — when a face detector is available — face visibility. If a
detector is NOT installed, face visibility is reported as "not checked" rather
than falsely claimed either way. Originals are never modified; crop/align
output is written to new files.

GPU-free and fully testable. Face detection uses OpenCV's Haar cascade only if
opencv-python is installed; otherwise the pipeline still runs and flags that a
manual face check is needed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

REQUIRED_PHOTOS = 3
MIN_DIMENSION = 256          # px, shortest side
RECOMMENDED_DIMENSION = 512

_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


@dataclass
class PhotoCheck:
    path: str
    ok: bool
    width: int = 0
    height: int = 0
    fmt: str = ""
    face_checked: bool = False
    faces_found: Optional[int] = None
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class IntakeResult:
    photos: list[PhotoCheck]
    ok: bool
    message: str = ""

    @property
    def usable(self) -> list[PhotoCheck]:
        return [p for p in self.photos if p.ok]


# ---------------------------------------------------------------------------
def _read_dimensions(path: Path) -> tuple[int, int, str] | None:
    try:
        from PIL import Image  # type: ignore
        with Image.open(path) as im:
            return im.width, im.height, (im.format or "").lower()
    except Exception:
        # Fallback: ffprobe.
        try:
            import json
            import subprocess
            from ..media.probe import ffprobe_path
            out = subprocess.run(
                [ffprobe_path(), "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height,codec_name",
                 "-print_format", "json", str(path)],
                capture_output=True, text=True, timeout=30)
            data = json.loads(out.stdout)
            s = (data.get("streams") or [{}])[0]
            return (int(s.get("width", 0)), int(s.get("height", 0)),
                    str(s.get("codec_name", "")))
        except Exception:
            return None


def _detect_faces(path: Path) -> Optional[int]:
    """Return face count if a detector is available, else None (not checked)."""
    try:
        import cv2  # type: ignore
    except Exception:
        return None
    try:
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        cascade = cv2.CascadeClassifier(cascade_path)
        img = cv2.imread(str(path))
        if img is None:
            return None
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5)
        return len(faces)
    except Exception:
        return None


def check_photo(path: str | Path) -> PhotoCheck:
    p = Path(path)
    check = PhotoCheck(path=str(p), ok=False)
    if not p.exists() or p.stat().st_size == 0:
        check.issues.append("File is missing or empty.")
        return check
    if p.suffix.lower() not in _IMAGE_EXT:
        check.issues.append(
            f"Unsupported image type '{p.suffix}'. Use PNG/JPG/WEBP.")
        return check
    dims = _read_dimensions(p)
    if dims is None:
        check.issues.append("Could not read image; file may be corrupt.")
        return check
    check.width, check.height, check.fmt = dims
    short = min(check.width, check.height)
    if short < MIN_DIMENSION:
        check.issues.append(
            f"Too small ({check.width}x{check.height}); shortest side must be "
            f">= {MIN_DIMENSION}px.")
    elif short < RECOMMENDED_DIMENSION:
        check.warnings.append(
            f"Low resolution ({check.width}x{check.height}); "
            f">= {RECOMMENDED_DIMENSION}px recommended for identity quality.")

    faces = _detect_faces(p)
    if faces is None:
        check.face_checked = False
        check.warnings.append(
            "Face visibility not auto-checked (no face detector installed); "
            "confirm the face is clearly visible, front-facing and unobscured.")
    else:
        check.face_checked = True
        check.faces_found = faces
        if faces == 0:
            check.issues.append("No face detected; use a clear, front-facing "
                                "photo.")
        elif faces > 1:
            check.warnings.append(
                f"{faces} faces detected; identity photos should show one "
                f"person.")

    check.ok = not check.issues
    return check


def intake_photos(paths: list[str | Path]) -> IntakeResult:
    """Validate a set of reference photos. Requires exactly three."""
    if len(paths) != REQUIRED_PHOTOS:
        return IntakeResult(
            photos=[check_photo(p) for p in paths], ok=False,
            message=f"Exactly {REQUIRED_PHOTOS} photos are required; "
                    f"{len(paths)} supplied.")
    checks = [check_photo(p) for p in paths]
    ok = all(c.ok for c in checks)
    if ok:
        msg = "All three photos passed validation."
    else:
        bad = [Path(c.path).name for c in checks if not c.ok]
        msg = f"Unusable photo(s): {', '.join(bad)}. Replace and retry."
    return IntakeResult(photos=checks, ok=ok, message=msg)
