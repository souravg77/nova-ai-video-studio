"""Three-photo intake + validation (Phase 4, P4.1).

Imports exactly three reference photos and validates each for:
  * readability / format,
  * minimum resolution,
  * not-too-dark / not-too-washed-out (basic quality),
  * face visibility (via OpenCV Haar cascade when available).

Unusable images are reported with a specific reason. The user approves the
selected identity references before anything else proceeds. Originals are
never modified — intake only reads them.

Honesty rule: if face detection is unavailable (no OpenCV), a photo is flagged
"face_unverified" (a warning), never silently treated as containing a face.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

REQUIRED_PHOTOS = 3
MIN_DIMENSION = 256          # px, shortest side
MIN_MEAN_BRIGHTNESS = 25     # 0..255; below = too dark
MAX_MEAN_BRIGHTNESS = 235    # above = washed out


@dataclass
class PhotoValidation:
    path: str
    ok: bool
    width: int = 0
    height: int = 0
    mean_brightness: float = 0.0
    faces_detected: Optional[int] = None  # None = detection unavailable
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return self.ok


@dataclass
class IntakeResult:
    photos: list[PhotoValidation]
    approved: bool = False

    @property
    def all_usable(self) -> bool:
        return (len(self.photos) == REQUIRED_PHOTOS
                and all(p.usable for p in self.photos))

    @property
    def unusable(self) -> list[PhotoValidation]:
        return [p for p in self.photos if not p.usable]


# ---------------------------------------------------------------------------
def _load_image(path: Path):
    try:
        from PIL import Image
    except Exception:
        return None, "PIL (Pillow) not installed; cannot read images."
    try:
        img = Image.open(path)
        img.load()
        return img.convert("RGB"), ""
    except Exception as exc:
        return None, f"Unreadable image: {exc}"


def _mean_brightness(img) -> float:
    try:
        gray = img.convert("L")
        hist = gray.histogram()
        total = sum(hist) or 1
        weighted = sum(i * c for i, c in enumerate(hist))
        return weighted / total
    except Exception:
        return 0.0


def _detect_faces(path: Path) -> Optional[int]:
    """Return face count, or None if detection is unavailable."""
    try:
        import cv2  # type: ignore
    except Exception:
        return None
    try:
        cascade_path = (Path(cv2.data.haarcascades)  # type: ignore
                        / "haarcascade_frontalface_default.xml")
        if not cascade_path.exists():
            return None
        clf = cv2.CascadeClassifier(str(cascade_path))
        img = cv2.imread(str(path))
        if img is None:
            return None
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        faces = clf.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5,
                                     minSize=(40, 40))
        return len(faces)
    except Exception:
        return None


def validate_photo(path: str | Path) -> PhotoValidation:
    p = Path(path)
    v = PhotoValidation(path=str(p), ok=True)
    if not p.exists() or p.stat().st_size == 0:
        v.ok = False
        v.reasons.append("File is missing or empty.")
        return v

    img, err = _load_image(p)
    if img is None:
        v.ok = False
        v.reasons.append(err)
        return v

    v.width, v.height = img.width, img.height
    if min(v.width, v.height) < MIN_DIMENSION:
        v.ok = False
        v.reasons.append(
            f"Resolution {v.width}x{v.height} is below the {MIN_DIMENSION}px "
            f"minimum shortest side.")

    v.mean_brightness = round(_mean_brightness(img), 1)
    if v.mean_brightness < MIN_MEAN_BRIGHTNESS:
        v.ok = False
        v.reasons.append(f"Image is too dark (brightness {v.mean_brightness}).")
    elif v.mean_brightness > MAX_MEAN_BRIGHTNESS:
        v.ok = False
        v.reasons.append(
            f"Image is washed out (brightness {v.mean_brightness}).")

    faces = _detect_faces(p)
    v.faces_detected = faces
    if faces is None:
        v.warnings.append(
            "Face detection unavailable (OpenCV/cascade missing); face "
            "visibility could not be verified.")
    elif faces == 0:
        v.ok = False
        v.reasons.append("No face detected; a clear single face is required.")
    elif faces > 1:
        v.warnings.append(
            f"{faces} faces detected; use a photo with a single clear face.")
    return v


def intake_photos(paths: list[str | Path]) -> IntakeResult:
    """Validate a set of candidate photos. Requires exactly three usable ones."""
    photos = [validate_photo(p) for p in paths]
    result = IntakeResult(photos=photos)
    return result


def approve_identity(result: IntakeResult) -> IntakeResult:
    """User approval gate. Only approvable when all three are usable."""
    if not result.all_usable:
        raise ValueError(
            "Cannot approve: need exactly three usable photos. "
            f"{len(result.unusable)} unusable.")
    result.approved = True
    return result
