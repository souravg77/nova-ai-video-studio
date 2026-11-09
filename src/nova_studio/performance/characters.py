"""Character Studio identity rules.

* Candidates are only ever appended; generating more never touches the
  approved design.
* Production may only use a character once the director approved a design.
* A locked character cannot be re-approved until it is explicitly unlocked,
  and the unlock is logged with its reason.
* Every change is recorded in the character's version history.
* An approved reference image *guides* generation. It is not a trained
  identity model, and nothing here claims otherwise.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rid() -> str:
    return "ref-" + uuid.uuid4().hex[:12]


class IdentityError(ValueError):
    """A Character Studio rule was violated."""


class CandidateSource(str, Enum):
    GENERATED = "generated"
    UPLOADED = "uploaded"


class Candidate(BaseModel):
    id: str
    image_path: str
    source: CandidateSource
    batch: int = 0
    rejected: bool = False
    # A labelled stand-in (e.g. offline test output), never real imagery.
    is_placeholder: bool = False


class ApprovedReference(BaseModel):
    reference_id: str
    candidate_id: str
    image_path: str
    version: int
    approved_at: str
    is_placeholder: bool = False
    # Optional extra views (three_quarter, side, back ...) keyed by name.
    views: dict[str, str] = Field(default_factory=dict)


class HistoryEntry(BaseModel):
    version: int
    at: str
    action: str
    note: str
    reference_id: Optional[str] = None


class VoiceProfile(BaseModel):
    voice_id: str = ""
    engine_id: Optional[str] = None
    language: str = "en"
    accent: str = ""
    speaking_style: str = ""


class Character(BaseModel):
    id: str
    name: str
    description: str = ""
    # Recorded so two-shots can keep relative scale (reference boards).
    height_cm: Optional[float] = None
    voice: VoiceProfile = Field(default_factory=VoiceProfile)
    candidates: list[Candidate] = Field(default_factory=list)
    approved: Optional[ApprovedReference] = None
    previous_approvals: list[ApprovedReference] = Field(default_factory=list)
    locked: bool = False
    history: list[HistoryEntry] = Field(default_factory=list)


def create_character(char_id: str, name: str, language: str = "en") -> Character:
    return Character(
        id=char_id, name=name, voice=VoiceProfile(language=language),
        history=[HistoryEntry(version=0, at=_now(), action="created",
                              note=f"Created {name}")])


def _current_version(c: Character) -> int:
    if c.approved:
        return c.approved.version
    return max((a.version for a in c.previous_approvals), default=0)


def _logged(c: Character, action: str, note: str,
            reference_id: Optional[str] = None) -> list[HistoryEntry]:
    return c.history + [HistoryEntry(version=_current_version(c), at=_now(),
                                     action=action, note=note,
                                     reference_id=reference_id)]


def add_candidates(c: Character, candidates: list[Candidate]) -> Character:
    """Append a new batch. Never replaces or edits the approved design."""
    if not candidates:
        return c
    batch = max((x.batch for x in c.candidates), default=0) + 1
    added = [x.model_copy(update={"batch": batch}) for x in candidates]
    uploaded = any(x.source == CandidateSource.UPLOADED for x in added)
    n = len(added)
    return c.model_copy(update={
        "candidates": c.candidates + added,
        "history": _logged(
            c, "reference_uploaded" if uploaded else "candidates_generated",
            f"{n} candidate{'' if n == 1 else 's'} added (batch {batch})"),
    })


def set_candidate_rejected(c: Character, candidate_id: str, rejected: bool) -> Character:
    if rejected and c.approved and c.approved.candidate_id == candidate_id:
        raise IdentityError("The approved design cannot be rejected. Approve a "
                            "different candidate first.")
    if not any(x.id == candidate_id for x in c.candidates):
        raise IdentityError("Candidate not found.")
    return c.model_copy(update={"candidates": [
        x.model_copy(update={"rejected": rejected}) if x.id == candidate_id else x
        for x in c.candidates]})


def approve_candidate(c: Character, candidate_id: str,
                      views: Optional[dict[str, str]] = None) -> Character:
    if c.locked:
        raise IdentityError(f"{c.name} is locked. Unlock the identity before "
                            f"approving a different design.")
    cand = next((x for x in c.candidates if x.id == candidate_id), None)
    if cand is None:
        raise IdentityError("Candidate not found.")
    if cand.rejected:
        raise IdentityError("This candidate was rejected. Restore it before approving.")
    version = _current_version(c) + 1
    ref = ApprovedReference(
        reference_id=_rid(), candidate_id=cand.id, image_path=cand.image_path,
        version=version, approved_at=_now(), is_placeholder=cand.is_placeholder,
        views={"front": cand.image_path, **(views or {})})
    previous = c.previous_approvals + ([c.approved] if c.approved else [])
    history = c.history + [HistoryEntry(
        version=version, at=_now(), action="approved",
        note=f"Approved design v{version}", reference_id=ref.reference_id)]
    return c.model_copy(update={"approved": ref, "previous_approvals": previous,
                                "history": history})


def lock_identity(c: Character) -> Character:
    if not c.approved:
        raise IdentityError("Approve a design before locking the identity.")
    if c.locked:
        return c
    return c.model_copy(update={"locked": True, "history": _logged(
        c, "locked", f"Locked identity at v{c.approved.version}",
        c.approved.reference_id)})


def unlock_identity(c: Character, reason: str) -> Character:
    if not c.locked:
        return c
    return c.model_copy(update={"locked": False, "history": _logged(
        c, "unlocked", f"Unlocked: {reason.strip() or 'no reason given'}")})


def set_voice(c: Character, engine_id: Optional[str], voice_id: str) -> Character:
    """Assign the character's speaking voice. Allowed while the visual
    identity is locked (the lock covers the approved design), and logged."""
    voice = c.voice.model_copy(update={"engine_id": engine_id or None,
                                       "voice_id": voice_id})
    note = (f"Voice set to {voice_id} ({engine_id})" if voice_id
            else "Voice cleared")
    return c.model_copy(update={"voice": voice,
                                "history": _logged(c, "voice_changed", note)})


class Readiness(BaseModel):
    ok: bool
    reason: str = ""
    reference_id: Optional[str] = None
    version: Optional[int] = None
    warnings: list[str] = Field(default_factory=list)


def production_readiness(c: Character) -> Readiness:
    """Whether a character may be used to generate production shots."""
    if not c.approved:
        return Readiness(ok=False, reason=f"{c.name} has no approved design. "
                         f"Approve one in Character Studio first.")
    warnings = []
    if not c.locked:
        warnings.append(f"{c.name} is approved but not locked; the approved "
                        f"design could still be changed.")
    if c.approved.is_placeholder:
        warnings.append(f"{c.name}'s approved design is a placeholder, not a "
                        f"real generated or uploaded image.")
    return Readiness(ok=True, reference_id=c.approved.reference_id,
                     version=c.approved.version, warnings=warnings)


def find_reference(c: Character, reference_id: str) -> Optional[ApprovedReference]:
    """The reference a shot was pinned to, even after a later re-approval."""
    if c.approved and c.approved.reference_id == reference_id:
        return c.approved
    return next((a for a in c.previous_approvals
                 if a.reference_id == reference_id), None)
