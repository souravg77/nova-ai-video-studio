"""Display text and actions for Character Studio and the shot plan.

Qt-free, so the wording and the rules about what each button may do are
unit-tested without a display. The widgets in ``character_studio.py`` and
``shot_plan.py`` only lay this out.

Honesty rules this module keeps:
* An approved image is described as a reference that guides generation,
  never as a trained model of the character.
* Placeholders are always labelled as placeholders.
* A shot the selected engines cannot perform reads as blocked, with reasons.
"""
from __future__ import annotations

import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..performance.characters import (
    Candidate, CandidateSource, Character, production_readiness)
from ..performance.planner import (
    DialogueLine, Route, Severity, Shot, ShotPlan)

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")

REFERENCE_NOTE = ("An approved image is a reference that guides generation. "
                  "It is not a trained model of the character.")

NO_IMAGE_ENGINE = ("Generating designs needs an image engine, and none is "
                   "included in this build yet. Upload a reference image "
                   "instead.")


# ---- characters --------------------------------------------------------------
def new_character_id(name: str, existing: list[Character]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-") or "character"
    taken = {c.id for c in existing}
    cid, n = base, 2
    while cid in taken:
        cid, n = f"{base}-{n}", n + 1
    return cid


def character_status(c: Character) -> str:
    if not c.approved:
        return "no approved design"
    s = f"approved v{c.approved.version}"
    if c.locked:
        s += ", locked"
    if c.approved.is_placeholder:
        s += ", placeholder"
    return s


def character_row(c: Character) -> str:
    return f"{c.name} ({character_status(c)})"


def candidate_row(c: Character, cand: Candidate) -> str:
    tags = []
    if c.approved and c.approved.candidate_id == cand.id:
        tags.append("APPROVED")
    if cand.rejected:
        tags.append("rejected")
    if cand.is_placeholder:
        tags.append("placeholder")
    tags.append("uploaded" if cand.source == CandidateSource.UPLOADED else "generated")
    n = next((i for i, x in enumerate(c.candidates, 1) if x.id == cand.id), 0)
    return f"Design {n}: batch {cand.batch}, {', '.join(tags)}"


def uploaded_candidate(path: Path, copy_to: Optional[Path] = None) -> Candidate:
    """A candidate for an uploaded image. With ``copy_to`` the image is copied
    into the project, so the approved design survives the original being
    moved or deleted."""
    if path.suffix.lower() not in IMAGE_SUFFIXES:
        raise ValueError(f"{path.name}: use a PNG, JPEG or WebP image.")
    if not path.is_file():
        raise ValueError(f"{path.name} does not exist.")
    cid = "cand-" + uuid.uuid4().hex[:12]
    stored = path
    if copy_to is not None:
        copy_to.mkdir(parents=True, exist_ok=True)
        stored = copy_to / f"{cid}{path.suffix.lower()}"
        try:
            shutil.copy2(path, stored)
        except OSError as exc:
            raise ValueError(f"Could not copy {path.name} into the project: {exc}")
    return Candidate(id=cid, image_path=str(stored), source=CandidateSource.UPLOADED)


def readiness_text(c: Character) -> str:
    r = production_readiness(c)
    lines = [("Ready for production shots." if r.ok else "Not ready: " + r.reason)]
    lines += ["Warning: " + w for w in r.warnings]
    return "\n".join(lines)


@dataclass(frozen=True)
class CandidateActions:
    approve: bool
    reject: bool
    restore: bool
    lock: bool
    unlock: bool
    approve_hint: str = ""


def candidate_actions(c: Optional[Character], cand: Optional[Candidate]) -> CandidateActions:
    """Which buttons are usable. The identity rules still enforce the same
    limits; this only avoids offering an action that would be refused."""
    if c is None:
        return CandidateActions(False, False, False, False, False)
    is_approved = bool(cand and c.approved and c.approved.candidate_id == cand.id)
    hint = ""
    if c.locked:
        hint = "Unlock the identity to approve a different design."
    elif cand is not None and cand.rejected:
        hint = "Restore this candidate before approving it."
    return CandidateActions(
        approve=bool(cand) and not c.locked and not cand.rejected and not is_approved,
        reject=bool(cand) and not cand.rejected and not is_approved,
        restore=bool(cand) and cand.rejected,
        lock=bool(c.approved) and not c.locked,
        unlock=c.locked,
        approve_hint=hint)


def history_rows(c: Character) -> list[str]:
    return [f"v{h.version}  {h.at[:16].replace('T', ' ')}  {h.note}"
            for h in reversed(c.history)]


# ---- shots -------------------------------------------------------------------
ROUTE_TEXT = {
    Route.NATIVE_AV: "One engine makes the picture and the spoken performance together.",
    Route.SEPARATE_PERFORMANCE: "Voice first, then the picture, then lip-sync for each speaker.",
    Route.VIDEO_ONLY: "No dialogue: picture only.",
}


def new_shot_id(shots: list[Shot]) -> str:
    n = len(shots) + 1
    taken = {s.id for s in shots}
    while f"shot-{n}" in taken:
        n += 1
    return f"shot-{n}"


def new_line(dialogue: list[DialogueLine], speaker_id: str, text: str) -> DialogueLine:
    if not text.strip():
        raise ValueError("The line is empty.")
    order = max((d.order for d in dialogue), default=0) + 1
    return DialogueLine(id=f"line-{uuid.uuid4().hex[:8]}", order=order,
                        speaker_id=speaker_id, text=text.strip())


def shot_row(shot: Shot, plan: Optional[ShotPlan]) -> str:
    state = "not planned" if plan is None else (
        "ready" if plan.can_proceed else f"blocked ({len(plan.blockers)})")
    lines = len(shot.dialogue_line_ids)
    return (f"{shot.id}: {shot.duration_s:g} s, {len(shot.character_ids)} "
            f"character(s), {lines} line(s), {state}")


def plan_lines(plan: ShotPlan) -> list[str]:
    out = ["Can proceed." if plan.can_proceed else
           "Blocked: this shot can't be made with the selected engines."]
    if plan.route is not None:
        out.append("Route: " + ROUTE_TEXT.get(plan.route, plan.route.value))
    for i, step in enumerate(plan.steps, 1):
        out.append(f"{i}. {step.description} [{step.engine_id}]")
    for lim in plan.limitations:
        label = {Severity.BLOCKER: "BLOCKER", Severity.WARNING: "Warning"}.get(
            lim.severity, "Note")
        out.append(f"{label}: {lim.message}")
    return out


# ---- reference views and sheets ---------------------------------------------
def copy_into_project(path: Path, dest_dir: Optional[Path], stem: str) -> Path:
    """Copy an image into the project so it survives the original moving."""
    if path.suffix.lower() not in IMAGE_SUFFIXES:
        raise ValueError(f"{path.name}: use a PNG, JPEG or WebP image.")
    if not path.is_file():
        raise ValueError(f"{path.name} does not exist.")
    if dest_dir is None:
        return path
    dest_dir.mkdir(parents=True, exist_ok=True)
    stored = dest_dir / f"{stem}-{uuid.uuid4().hex[:8]}{path.suffix.lower()}"
    try:
        shutil.copy2(path, stored)
    except OSError as exc:
        raise ValueError(f"Could not copy {path.name} into the project: {exc}")
    return stored


def view_rows(c: Optional[Character]) -> list[tuple[str, str]]:
    """(slot, text) for each reference view slot the user can fill. The front
    view is the approved design itself, so it is listed but not editable."""
    from ..sheets.views import ALL_SLOTS, slot_label, view_path
    if c is None or c.approved is None:
        return []
    rows = []
    for slot in ALL_SLOTS:
        if slot == "front":
            continue
        p = view_path(c, slot)
        rows.append((slot, f"{slot_label(slot)}: "
                           + (Path(p).name if p else "empty")))
    return rows


def views_hint(c: Optional[Character]) -> str:
    if c is None:
        return ""
    if c.approved is None:
        return "Approve a design first; views belong to the approved design."
    if c.locked:
        return "Unlock the identity to change its reference views."
    return ("Add your own image for each view. Generating views needs an "
            "image engine, which this build doesn't include.")


def sheet_path(media_dir: Optional[Path], c: Character) -> Path:
    base = (media_dir / c.id) if media_dir else Path.cwd()
    tag = f"v{c.approved.version}" if c.approved else "draft"
    return base / f"{c.id}_reference_sheet_{tag}.png"


def sheet_summary(rep) -> str:
    from ..sheets.views import ALL_SLOTS
    if not rep.approved:
        head = "Draft sheet made: this character has no approved design yet."
    else:
        head = (f"Reference sheet for v{rep.version} made: "
                f"{len(ALL_SLOTS) - len(rep.missing)} of {len(ALL_SLOTS)} views filled.")
    lines = [head, f"Saved to {rep.path}"]
    lines += ["Warning: " + w for w in rep.warnings]
    return "\n".join(lines)
