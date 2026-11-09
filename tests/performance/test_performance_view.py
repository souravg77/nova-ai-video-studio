"""Character Studio / shot plan wording and button rules (no display needed)."""
from pathlib import Path

import pytest

from nova_studio.performance.characters import (
    Candidate, CandidateSource, add_candidates, approve_candidate,
    create_character, lock_identity, set_candidate_rejected)
from nova_studio.performance.planner import (
    Limitation, Route, Severity, Shot, ShotPlan)
from nova_studio.ui import performance_view as view


def _with_two(placeholder=False):
    c = create_character("maya", "Maya")
    return add_candidates(c, [
        Candidate(id="a", image_path="/x/a.png", source=CandidateSource.UPLOADED,
                  is_placeholder=placeholder),
        Candidate(id="b", image_path="/x/b.png", source=CandidateSource.UPLOADED)])


def test_ids_are_readable_and_unique():
    chars = [create_character("maya", "Maya")]
    assert view.new_character_id("Maya", chars) == "maya-2"
    assert view.new_character_id("  Dr. Leo Ortiz ", chars) == "dr-leo-ortiz"
    assert view.new_character_id("!!!", []) == "character"
    shots = [Shot(id="shot-2", duration_s=5)]
    assert view.new_shot_id(shots) == "shot-3"


def test_status_never_claims_training_and_labels_placeholders():
    c = _with_two(placeholder=True)
    assert view.character_status(c) == "no approved design"
    assert "Not ready" in view.readiness_text(c)
    c = lock_identity(approve_candidate(c, "a"))
    assert view.character_status(c) == "approved v1, locked, placeholder"
    assert "placeholder" in view.readiness_text(c)
    assert "not a trained model" in view.REFERENCE_NOTE
    assert "train" not in view.readiness_text(c).lower()
    row = view.candidate_row(c, c.candidates[0])
    assert row.startswith("Design 1:") and "APPROVED" in row
    assert "placeholder" in row and "batch 1" in row


def test_buttons_follow_identity_rules():
    c = _with_two()
    a, b = c.candidates
    acts = view.candidate_actions(c, a)
    assert acts.approve and acts.reject and not acts.restore and not acts.lock
    c = approve_candidate(c, "a")
    acts = view.candidate_actions(c, c.candidates[0])
    assert not acts.approve and not acts.reject and acts.lock  # approved one
    c = lock_identity(c)
    acts = view.candidate_actions(c, c.candidates[1])
    assert not acts.approve and acts.unlock and "Unlock" in acts.approve_hint
    c = set_candidate_rejected(c, "b", True)
    acts = view.candidate_actions(c, c.candidates[1])
    assert acts.restore and not acts.reject
    assert view.candidate_actions(None, None) == view.CandidateActions(
        False, False, False, False, False)


def test_uploads_must_be_real_images(tmp_path):
    img = tmp_path / "maya.png"; img.write_bytes(b"\x89PNG")
    cand = view.uploaded_candidate(img)
    assert cand.source == CandidateSource.UPLOADED and not cand.is_placeholder
    with pytest.raises(ValueError, match="PNG, JPEG or WebP"):
        view.uploaded_candidate(tmp_path / "notes.txt")
    with pytest.raises(ValueError, match="does not exist"):
        view.uploaded_candidate(tmp_path / "gone.png")


def test_uploads_are_copied_into_the_project(tmp_path):
    img = tmp_path / "Maya Front.PNG"; img.write_bytes(b"\x89PNG")
    dest = tmp_path / "project" / "characters" / "maya"
    cand = view.uploaded_candidate(img, dest)
    stored = Path(cand.image_path)
    assert stored.parent == dest and stored.suffix == ".png"
    assert stored.read_bytes() == b"\x89PNG"
    img.unlink()                       # the original going away is harmless
    assert stored.exists()


def test_lines_and_plan_text():
    line = view.new_line([], "maya", "  Hello.  ")
    assert line.text == "Hello." and line.order == 1
    with pytest.raises(ValueError):
        view.new_line([line], "maya", "   ")
    blocked = ShotPlan(shot_id="s", route=None, steps=[], limitations=[
        Limitation(severity=Severity.BLOCKER, code="x", message="No voice engine.")])
    text = view.plan_lines(blocked)
    assert text[0].startswith("Blocked") and "BLOCKER: No voice engine." in text
    shot = Shot(id="shot-1", duration_s=6, character_ids=["maya"])
    assert "blocked (1)" in view.shot_row(shot, blocked)
    ok = ShotPlan(shot_id="s", route=Route.VIDEO_ONLY, steps=[], limitations=[])
    assert view.plan_lines(ok)[:2] == ["Can proceed.", "Route: No dialogue: picture only."]
