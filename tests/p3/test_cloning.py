"""Voice cloning safeguards block unauthorized requests."""
from nova_studio.voice.cloning import (ConsentLog, ConsentRecord,
                                       UseScope, VerificationStatus,
                                       evaluate_cloning)


def _record(use=UseScope.PERSONAL, verif=VerificationStatus.VERIFIED,
            complete=True):
    if complete:
        return ConsentRecord("Alex", "passport#A1", "form#42", use, verif,
                             "xtts_v2")
    return ConsentRecord("", "", "", use, verif, "xtts_v2")


def test_unapproved_engine_blocked():
    d = evaluate_cloning("piper", _record(), UseScope.PERSONAL)
    assert d.allowed is False


def test_commercial_use_blocked_noncommercial_license():
    d = evaluate_cloning("xtts_v2", _record(use=UseScope.COMMERCIAL),
                         UseScope.COMMERCIAL)
    assert d.allowed is False
    assert "non-commercial" in d.reason.lower() or "licensed" in d.reason.lower()


def test_missing_record_blocked():
    assert evaluate_cloning("xtts_v2", None, UseScope.PERSONAL).allowed is False


def test_incomplete_record_blocked():
    d = evaluate_cloning("xtts_v2", _record(complete=False), UseScope.PERSONAL)
    assert d.allowed is False


def test_unverified_blocked():
    d = evaluate_cloning("xtts_v2",
                         _record(verif=VerificationStatus.PENDING),
                         UseScope.PERSONAL)
    assert d.allowed is False


def test_authorized_personal_allowed():
    d = evaluate_cloning("xtts_v2", _record(), UseScope.PERSONAL)
    assert d.allowed is True


def test_consent_log_is_auditable(tmp_path):
    log = ConsentLog(tmp_path / "consent.log")
    rec = _record()
    d = evaluate_cloning("xtts_v2", rec, UseScope.PERSONAL)
    log.record(rec, d)
    entries = log.entries()
    assert len(entries) == 1
    assert entries[0]["decision"]["allowed"] is True
    assert entries[0]["record"]["speaker_name"] == "Alex"
