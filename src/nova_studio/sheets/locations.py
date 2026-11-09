"""Location references: camera angles and textures, approved as a set.

Slots follow the location sheets in roadmap 7a: four camera angles that can
serve as shot start frames, plus texture close-ups. A location is edited
while unapproved; approval locks its views (the version number goes up),
and unapproving is required to change them again.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..director.model import LocationRef

ANGLES = ("front", "left", "right", "reverse_wide")
TEXTURES = ("texture_1", "texture_2", "texture_3", "texture_4")
ALL_LOCATION_SLOTS = ANGLES + TEXTURES
LABELS = {"front": "Frontal view", "left": "Left angle", "right": "Right angle",
          "reverse_wide": "Reverse wide", "texture_1": "Texture 1",
          "texture_2": "Texture 2", "texture_3": "Texture 3", "texture_4": "Texture 4"}


class LocationError(ValueError):
    pass


def _check_image(path: str | Path) -> None:
    from PIL import Image, UnidentifiedImageError
    p = Path(path)
    if not p.is_file():
        raise LocationError(f"Image not found: {p}")
    try:
        with Image.open(p) as im:
            im.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise LocationError(f"Not a readable image: {p.name} ({exc})") from exc


def set_location_view(loc: LocationRef, slot: str, image_path: str | Path) -> LocationRef:
    if slot not in ALL_LOCATION_SLOTS:
        raise LocationError(f"Unknown location slot: {slot}")
    if loc.approved:
        raise LocationError(f"{loc.name} is approved. Unapprove it to change its views.")
    _check_image(image_path)
    return loc.model_copy(update={"views": {**loc.views, slot: str(image_path)}})


def clear_location_view(loc: LocationRef, slot: str) -> LocationRef:
    if loc.approved:
        raise LocationError(f"{loc.name} is approved. Unapprove it to change its views.")
    return loc.model_copy(update={"views": {k: v for k, v in loc.views.items() if k != slot}})


def approve_location(loc: LocationRef) -> LocationRef:
    if not loc.views.get("front"):
        raise LocationError(f"Add a frontal view of {loc.name} before approving it.")
    missing = [s for s, p in loc.views.items() if not Path(p).is_file()]
    if missing:
        raise LocationError(f"{loc.name}: image file missing for {', '.join(missing)}.")
    return loc.model_copy(update={"approved": True, "version": loc.version + 1,
                                  "approved_at": datetime.now(timezone.utc).isoformat()})


def unapprove_location(loc: LocationRef) -> LocationRef:
    return loc.model_copy(update={"approved": False})


def approved_frame(loc: Optional[LocationRef]) -> Optional[str]:
    """The approved frontal view, if this location is approved and on disk."""
    if loc is None or not loc.approved:
        return None
    p = loc.views.get("front")
    return p if p and Path(p).is_file() else None


def put_location(director, loc: LocationRef) -> None:
    for i, existing in enumerate(director.locations):
        if existing.id == loc.id:
            director.locations[i] = loc
            return
    director.locations.append(loc)
