"""Voice cloning consent + safeguards (Phase 3, P3.5).

Voice cloning is a distinct, higher-risk capability. This module enforces that
cloning can proceed ONLY when:
  1. an approved, compatible cloning engine is selected,
  2. the engine's license permits the intended use,
  3. a consent record exists with: speaker identity, authorization evidence,
     verification status, and the permitted use, and
  4. that record is marked verified.

Any missing element BLOCKS cloning. All decisions are recorded to an auditable
JSON log. Nothing here performs cloning itself — it gates it.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class UseScope(str, Enum):
    PERSONAL = "personal"
    INTERNAL = "internal"
    COMMERCIAL = "commercial"


class VerificationStatus(str, Enum):
    UNVERIFIED = "unverified"
    PENDING = "pending"
    VERIFIED = "verified"


@dataclass
class ConsentRecord:
    speaker_name: str
    speaker_identity_ref: str          # how identity was established
    authorization_evidence: str        # signed form id / document reference
    permitted_use: UseScope
    verification: VerificationStatus = VerificationStatus.UNVERIFIED
    engine_id: str = ""
    reference_sample_path: str = ""
    recorded_at: str = field(default_factory=_now)
    record_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    notes: str = ""

    def is_complete(self) -> bool:
        return bool(self.speaker_name and self.speaker_identity_ref
                    and self.authorization_evidence)


@dataclass
class CloningDecision:
    allowed: bool
    reason: str
    record_id: str = ""


# Engines explicitly approved for cloning AND the uses their license permits.
# XTTS-v2 is non-commercial per the roadmap: never approved for COMMERCIAL use.
_APPROVED_CLONING = {
    # engine_id: set of permitted UseScope values
    # (empty by default — no engine is cleared for commercial cloning until a
    # license review records it here.)
    "xtts_v2": {UseScope.PERSONAL, UseScope.INTERNAL},
}


def evaluate_cloning(engine_id: str, record: Optional[ConsentRecord],
                     intended_use: UseScope) -> CloningDecision:
    """Decide whether a cloning request may proceed. Blocks on any gap."""
    if engine_id not in _APPROVED_CLONING:
        return CloningDecision(
            False,
            f"Engine '{engine_id}' is not an approved cloning engine. Cloning "
            f"is blocked.")
    permitted = _APPROVED_CLONING[engine_id]
    if intended_use not in permitted:
        return CloningDecision(
            False,
            f"Engine '{engine_id}' is not licensed for {intended_use.value} "
            f"use (permitted: {sorted(u.value for u in permitted)}). For "
            f"XTTS-v2 the published license is non-commercial. Blocked.")
    if record is None:
        return CloningDecision(
            False, "No consent record supplied. Cloning requires a recorded, "
                   "verified authorization. Blocked.")
    if not record.is_complete():
        return CloningDecision(
            False, "Consent record is incomplete (needs speaker identity, "
                   "authorization evidence and permitted use). Blocked.",
            record_id=record.record_id)
    if record.verification != VerificationStatus.VERIFIED:
        return CloningDecision(
            False, f"Speaker verification is '{record.verification.value}', not "
                   f"'verified'. Cloning is blocked until verification "
                   f"completes.", record_id=record.record_id)
    if record.permitted_use != intended_use:
        return CloningDecision(
            False, f"Consent permits '{record.permitted_use.value}' use but "
                   f"the request is '{intended_use.value}'. Blocked.",
            record_id=record.record_id)
    return CloningDecision(
        True, "Authorized: approved engine, licensed use, complete and "
              "verified consent.", record_id=record.record_id)


class ConsentLog:
    """Append-only auditable log of cloning decisions + consent records."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, record: ConsentRecord, decision: CloningDecision) -> None:
        entry = {
            "at": _now(),
            "record": {
                "record_id": record.record_id,
                "speaker_name": record.speaker_name,
                "speaker_identity_ref": record.speaker_identity_ref,
                "authorization_evidence": record.authorization_evidence,
                "permitted_use": record.permitted_use.value,
                "verification": record.verification.value,
                "engine_id": record.engine_id,
                "recorded_at": record.recorded_at,
            },
            "decision": {"allowed": decision.allowed, "reason": decision.reason},
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def entries(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in
                self.path.read_text(encoding="utf-8").splitlines() if line.strip()]
