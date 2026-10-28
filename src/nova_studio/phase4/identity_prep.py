"""Identity preparation (Phase 4, P4.2).

Crops/aligns faces and prepares reference images for the generation engine.
ALWAYS works on copies — the original files are never modified. When face
detection is available, the crop is centred on the detected face with margin;
otherwise it falls back to a centre square crop and flags that the crop is
unaligned (honest, not pretending alignment happened).

Background removal is optional and only attempted when a supporting library is
installed; otherwise it is reported as skipped, not silently ignored.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class PreparedImage:
    source_path: str
    output_path: str
    ok: bool
    aligned: bool = False          # True only if a face drove the crop
    size: int = 0
    background_removed: bool = False
    notes: list[str] = field(default_factory=list)


def _face_box(path: Path):
    """Return (x, y, w, h) of the largest face, or None."""
    try:
        import cv2  # type: ignore
        cascade = (Path(cv2.data.haarcascades)  # type: ignore
                   / "haarcascade_frontalface_default.xml")
        if not cascade.exists():
            return None
        clf = cv2.CascadeClassifier(str(cascade))
        img = cv2.imread(str(path))
        if img is None:
            return None
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        faces = clf.detectMultiScale(gray, 1.1, 5, minSize=(40, 40))
        if len(faces) == 0:
            return None
        return max(faces, key=lambda f: f[2] * f[3])  # largest by area
    except Exception:
        return None


def prepare_image(source: str | Path, out_dir: str | Path,
                  target_size: int = 512,
                  remove_background: bool = False) -> PreparedImage:
    src = Path(source)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    out_path = out / f"prepped_{src.stem}.png"

    try:
        from PIL import Image
    except Exception:
        return PreparedImage(str(src), "", ok=False,
                             notes=["PIL not installed; cannot prepare image."])

    try:
        # Read a COPY into memory; the original on disk is untouched.
        img = Image.open(src).convert("RGB")
    except Exception as exc:
        return PreparedImage(str(src), "", ok=False,
                             notes=[f"Unreadable image: {exc}"])

    prepared = PreparedImage(str(src), str(out_path), ok=True,
                             size=target_size)

    box = _face_box(src)
    if box is not None:
        x, y, w, h = [int(v) for v in box]
        # Expand around the face for head-and-shoulders framing.
        cx, cy = x + w // 2, y + h // 2
        side = int(max(w, h) * 1.8)
        left = max(0, cx - side // 2)
        top = max(0, cy - side // 2)
        right = min(img.width, left + side)
        bottom = min(img.height, top + side)
        img = img.crop((left, top, right, bottom))
        prepared.aligned = True
    else:
        # Centre square crop; NOT a real face alignment.
        side = min(img.width, img.height)
        left = (img.width - side) // 2
        top = (img.height - side) // 2
        img = img.crop((left, top, left + side, top + side))
        prepared.aligned = False
        prepared.notes.append(
            "No face detected or detection unavailable; used a centre crop. "
            "Image is NOT face-aligned.")

    img = img.resize((target_size, target_size))

    if remove_background:
        removed = _try_remove_background(img)
        if removed is not None:
            img = removed
            prepared.background_removed = True
        else:
            prepared.notes.append(
                "Background removal requested but no supporting library is "
                "installed; skipped.")

    try:
        img.save(out_path)
    except Exception as exc:
        return PreparedImage(str(src), "", ok=False,
                             notes=[f"Could not write prepared image: {exc}"])
    return prepared


def _try_remove_background(img):
    """Return a background-removed image, or None if unavailable."""
    try:
        from rembg import remove  # type: ignore
        return remove(img)
    except Exception:
        return None


def prepare_all(sources: list[str | Path], out_dir: str | Path,
                target_size: int = 512,
                remove_background: bool = False) -> list[PreparedImage]:
    return [prepare_image(s, out_dir, target_size, remove_background)
            for s in sources]
