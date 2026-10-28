"""Likeness consent + provenance (Phase 4, P4.5).

Talking-head generation uses a real person's likeness AND voice, so it needs
authorization for BOTH. This module:
  * requires a likeness-consent record (authorization to use the depicted
    person's face), reusing the voice-consent model for the voice side,
  * blocks generation when either authorization is missing or unverified, and
  * records a provenance manifest: source photos (hashed), selected voice,
    model/engine version, generation settings and the consent decision — so a
    produced clip can be traced back to its authorization.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..voice.cloning import (ConsentRecord, UseScope, VerificationStatus)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: str | Path) -> str:
    p = Path(path)
    if not p.exists():
        return ""
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class LikenessConsent:
    """Authorization to use a depicted person's likeness."""
    subject_name: str
    identity_ref: str              # how the subject's identity was established
    authorization_evidence: str    # signed release id / document reference
    permitted_use: UseScope
    verification: VerificationStatus = VerificationStatus.UNVERIFIED
    recorded_at: str = field(default_factory=_now)
    record_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def is_complete(self) -> bool:
        return bool(self.subject_name and self.identity_ref
                    and self.authorization_evidence)


@dataclass
class GenerationProvenance:
    source_photos: list[str]
    photo_hashes: list[str]
    voice_engine_id: str
    voice_path: str
    gen_engine_id: str
    gen_engine_version: str
    settings: dict
    likeness_record_id: str
    voice_record_id: str
    created_at: str = field(default_factory=_now)
    provenance_id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass
class AuthorizationDecision:
    allowed: bool
    reason: str
    likeness_record_id: str = ""
    voice_record_id: str = ""


def authorize_generation(likeness: Optional[LikenessConsent],
                         voice_consent: Optional[ConsentRecord],
                         intended_use: UseScope) -> AuthorizationDecision:
    """Both likeness AND voice must be authorized + verified for the use."""
    # Likeness side.
    if likeness is None:
        return AuthorizationDecision(
            False, "No likeness-consent record. Authorization to use the "
                   "depicted person's face is required. Blocked.")
    if not likeness.is_complete():
        return AuthorizationDecision(
            False, "Likeness consent is incomplete (needs subject identity, "
                   "authorization evidence and permitted use). Blocked.",
            likeness_record_id=likeness.record_id)
    if likeness.verification != VerificationStatus.VERIFIED:
        return AuthorizationDecision(
            False, f"Likeness verification is '{likeness.verification.value}', "
                   f"not 'verified'. Blocked.",
            likeness_record_id=likeness.record_id)
    if likeness.permitted_use != intended_use:
        return AuthorizationDecision(
            False, f"Likeness consent permits '{likeness.permitted_use.value}' "
                   f"use but the request is '{intended_use.value}'. Blocked.",
            likeness_record_id=likeness.record_id)

    # Voice side (reuses the cloning consent record).
    if voice_consent is None:
        return AuthorizationDecision(
            False, "No voice-consent record. Authorization to use the person's "
                   "voice is required. Blocked.",
            likeness_record_id=likeness.record_id)
    if not voice_consent.is_complete():
        return AuthorizationDecision(
            False, "Voice consent is incomplete. Blocked.",
            likeness_record_id=likeness.record_id,
            voice_record_id=voice_consent.record_id)
    if voice_consent.verification != VerificationStatus.VERIFIED:
        return AuthorizationDecision(
            False, f"Voice verification is '{voice_consent.verification.value}', "
                   f"not 'verified'. Blocked.",
            likeness_record_id=likeness.record_id,
            voice_record_id=voice_consent.record_id)
    if voice_consent.permitted_use != intended_use:
        return AuthorizationDecision(
            False, f"Voice consent permits '{voice_consent.permitted_use.value}' "
                   f"but the request is '{intended_use.value}'. Blocked.",
            likeness_record_id=likeness.record_id,
            voice_record_id=voice_consent.record_id)

    return AuthorizationDecision(
        True, "Authorized: likeness and voice consent complete and verified "
              "for the intended use.",
        likeness_record_id=likeness.record_id,
        voice_record_id=voice_consent.record_id)


def build_provenance(source_photos: list[str], voice_engine_id: str,
                     voice_path: str, gen_engine_id: str,
                     gen_engine_version: str, settings: dict,
                     likeness_record_id: str,
                     voice_record_id: str) -> GenerationProvenance:
    return GenerationProvenance(
        source_photos=[str(p) for p in source_photos],
        photo_hashes=[_sha256(p) for p in source_photos],
        voice_engine_id=voice_engine_id, voice_path=voice_path,
        gen_engine_id=gen_engine_id, gen_engine_version=gen_engine_version,
        settings=settings, likeness_record_id=likeness_record_id,
        voice_record_id=voice_record_id)


def write_provenance(prov: GenerationProvenance, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "provenance_id": prov.provenance_id,
        "created_at": prov.created_at,
        "source_photos": prov.source_photos,
        "photo_hashes": prov.photo_hashes,
        "voice_engine_id": prov.voice_engine_id,
        "voice_path": prov.voice_path,
        "gen_engine_id": prov.gen_engine_id,
        "gen_engine_version": prov.gen_engine_version,
        "settings": prov.settings,
        "likeness_record_id": prov.likeness_record_id,
        "voice_record_id": prov.voice_record_id,
    }, indent=2), encoding="utf-8")
    return p
