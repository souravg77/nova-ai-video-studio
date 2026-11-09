"""Character Studio identity rules."""
import pytest

from nova_studio.performance.characters import (
    Candidate, CandidateSource, IdentityError, add_candidates, approve_candidate,
    create_character, find_reference, lock_identity, production_readiness,
    set_candidate_rejected, unlock_identity)


def _cands(*ids, placeholder=False, source=CandidateSource.GENERATED):
    return [Candidate(id=i, image_path=f"/img/{i}.png", source=source,
                      is_placeholder=placeholder) for i in ids]


def _approved(name="Maya"):
    c = add_candidates(create_character("char-maya", name), _cands("a", "b"))
    return approve_candidate(c, "a")


def test_unapproved_character_cannot_be_used():
    r = production_readiness(create_character("char-x", "X"))
    assert not r.ok and "no approved design" in r.reason


def test_generating_more_never_replaces_approved_design():
    c = _approved()
    ref = c.approved.reference_id
    c = add_candidates(c, _cands("c", "d"))
    assert c.approved.reference_id == ref
    assert [x.batch for x in c.candidates] == [1, 1, 2, 2]


def test_locked_identity_cannot_be_reapproved_until_unlocked_and_logged():
    c = lock_identity(_approved())
    with pytest.raises(IdentityError, match="locked"):
        approve_candidate(c, "b")
    c = unlock_identity(c, "new wardrobe")
    assert c.history[-1].action == "unlocked" and "new wardrobe" in c.history[-1].note
    c = approve_candidate(c, "b")
    assert c.approved.version == 2 and c.approved.candidate_id == "b"


def test_reapproval_keeps_old_reference_findable_for_pinned_shots():
    c = _approved()
    old = c.approved.reference_id
    c = approve_candidate(c, "b")
    assert find_reference(c, old).version == 1
    assert find_reference(c, "ref-missing") is None


def test_approved_design_cannot_be_rejected_and_rejected_cannot_be_approved():
    c = _approved()
    with pytest.raises(IdentityError):
        set_candidate_rejected(c, "a", True)
    c = set_candidate_rejected(c, "b", True)
    with pytest.raises(IdentityError, match="rejected"):
        approve_candidate(c, "b")


def test_placeholder_and_unlocked_are_warned_not_hidden():
    c = add_candidates(create_character("char-p", "P"), _cands("p", placeholder=True))
    r = production_readiness(approve_candidate(c, "p"))
    assert r.ok
    assert any("placeholder" in w for w in r.warnings)
    assert any("not locked" in w for w in r.warnings)


def test_upload_is_logged_as_reference_upload():
    c = add_candidates(create_character("char-u", "U"),
                       _cands("u", source=CandidateSource.UPLOADED))
    assert c.history[-1].action == "reference_uploaded"
