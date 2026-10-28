"""Likeness + voice authorization and provenance manifest."""
import json

from nova_studio.phase4.provenance import (LikenessConsent,
                                          authorize_generation,
                                          build_provenance, write_provenance)
from nova_studio.voice.cloning import (ConsentRecord, UseScope,
                                      VerificationStatus)


def _likeness(use=UseScope.PERSONAL, verif=VerificationStatus.VERIFIED,
              complete=True):
    if complete:
        return LikenessConsent("Alex", "passport#A", "release#1", use, verif)
    return LikenessConsent("", "", "", use, verif)


def _voice(use=UseScope.PERSONAL, verif=VerificationStatus.VERIFIED):
    return ConsentRecord("Alex", "passport#A", "form#2", use, verif, "xtts_v2")


def test_no_likeness_blocks():
    assert authorize_generation(None, _voice(), UseScope.PERSONAL).allowed is False


def test_likeness_without_voice_blocks():
    d = authorize_generation(_likeness(), None, UseScope.PERSONAL)
    assert d.allowed is False


def test_unverified_likeness_blocks():
    d = authorize_generation(
        _likeness(verif=VerificationStatus.PENDING), _voice(), UseScope.PERSONAL)
    assert d.allowed is False


def test_use_mismatch_blocks():
    d = authorize_generation(
        _likeness(use=UseScope.PERSONAL), _voice(use=UseScope.PERSONAL),
        UseScope.COMMERCIAL)
    assert d.allowed is False


def test_both_verified_allows():
    d = authorize_generation(_likeness(), _voice(), UseScope.PERSONAL)
    assert d.allowed is True
    assert d.likeness_record_id and d.voice_record_id


def test_provenance_records_hashes(tmp_path):
    photo = tmp_path / "p.png"
    photo.write_bytes(b"fake-image-bytes")
    prov = build_provenance(
        [str(photo)], "piper", "/v.onnx", "sadtalker", "1.0",
        {"res": "512", "frames": 30}, "lk1", "vc1")
    assert len(prov.photo_hashes[0]) == 64  # sha256 hex
    out = write_provenance(prov, tmp_path / "prov.json")
    data = json.loads(out.read_text())
    assert data["gen_engine_id"] == "sadtalker"
    assert data["likeness_record_id"] == "lk1"
    assert data["voice_record_id"] == "vc1"
    assert data["settings"]["frames"] == 30
