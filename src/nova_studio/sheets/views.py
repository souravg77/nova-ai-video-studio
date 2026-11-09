"""Reference view slots on a character's approved design.

Turnaround slots plus one expression slot per basic emotion. Views belong to
the approved reference they were added to: approving a new design starts a
new set, and a locked identity cannot have its views changed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..performance.characters import Character, HistoryEntry, IdentityError

TURNAROUND = ("front", "three_quarter", "side", "three_quarter_back", "back")
EXPRESSIONS = ("neutral", "happiness", "sadness", "surprise", "fear",
               "disgust", "anger")
EXPRESSION_PREFIX = "expression:"

LABELS = {"front": "Front", "three_quarter": "3/4 front", "side": "Side",
          "three_quarter_back": "3/4 back", "back": "Back"}


def expression_slot(emotion: str) -> str:
    return f"{EXPRESSION_PREFIX}{emotion}"


ALL_SLOTS = TURNAROUND + tuple(expression_slot(e) for e in EXPRESSIONS)


def slot_label(slot: str) -> str:
    if slot.startswith(EXPRESSION_PREFIX):
        return slot[len(EXPRESSION_PREFIX):].capitalize()
    return LABELS.get(slot, slot)


def _check_image(path: str | Path) -> None:
    from PIL import Image, UnidentifiedImageError
    p = Path(path)
    if not p.is_file():
        raise IdentityError(f"Image not found: {p}")
    try:
        with Image.open(p) as im:
            im.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise IdentityError(f"Not a readable image: {p.name} ({exc})") from exc


def _editable(c: Character) -> None:
    if not c.approved:
        raise IdentityError(f"Approve a design for {c.name} before adding reference views.")
    if c.locked:
        raise IdentityError(f"{c.name} is locked. Unlock the identity to change its reference views.")


def _log(c: Character, action: str, note: str) -> list[HistoryEntry]:
    return c.history + [HistoryEntry(
        version=c.approved.version, at=datetime.now(timezone.utc).isoformat(),
        action=action, note=note, reference_id=c.approved.reference_id)]


def set_view(c: Character, slot: str, image_path: str | Path) -> Character:
    """Attach an image to a view slot of the approved design (returns a copy)."""
    if slot not in ALL_SLOTS:
        raise IdentityError(f"Unknown view slot: {slot}")
    _editable(c)
    _check_image(image_path)
    ref = c.approved.model_copy(update={"views": {**c.approved.views, slot: str(image_path)}})
    return c.model_copy(update={"approved": ref, "history": _log(
        c, "view_set", f"{slot_label(slot)} view set to {Path(image_path).name}")})


def clear_view(c: Character, slot: str) -> Character:
    _editable(c)
    if slot == "front":
        raise IdentityError("The front view is the approved design itself; approve a different design to change it.")
    views = {k: v for k, v in c.approved.views.items() if k != slot}
    ref = c.approved.model_copy(update={"views": views})
    return c.model_copy(update={"approved": ref, "history": _log(
        c, "view_cleared", f"{slot_label(slot)} view removed")})


def view_path(c: Character, slot: str) -> Optional[str]:
    if not c.approved:
        return None
    return c.approved.views.get(slot)


def missing_slots(c: Character) -> list[str]:
    return [s for s in ALL_SLOTS if not view_path(c, s)]
