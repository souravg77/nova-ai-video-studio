"""Reference views and sheets: approved data only, nothing invented."""
import hashlib

import pytest
from PIL import Image

from nova_studio.performance.characters import (
    Candidate, CandidateSource, IdentityError, add_candidates, approve_candidate,
    create_character, lock_identity, unlock_identity)
from nova_studio.sheets.compose import H, W, render_sheet
from nova_studio.sheets.views import (ALL_SLOTS, clear_view, expression_slot,
                                      missing_slots, set_view, view_path)


@pytest.fixture
def img(tmp_path):
    p = tmp_path / "portrait.png"
    im = Image.new("RGB", (200, 300), (180, 140, 100))
    for x in range(100):
        for y in range(300):
            im.putpixel((x, y), (40, 60, 90))
    im.save(p)
    return str(p)


def _approved(img):
    c = create_character("c1", "Elaine")
    c = add_candidates(c, [Candidate(id="k1", image_path=img, source=CandidateSource.UPLOADED)])
    return approve_candidate(c, "k1")


def test_views_need_an_approved_unlocked_design(img):
    c = create_character("c1", "Elaine")
    with pytest.raises(IdentityError, match="Approve a design"):
        set_view(c, "side", img)
    c = lock_identity(_approved(img))
    with pytest.raises(IdentityError, match="locked"):
        set_view(c, "side", img)
    c = unlock_identity(c, "add side view")
    c = set_view(c, "side", img)
    assert view_path(c, "side") == img
    assert c.history[-1].action == "view_set"


def test_bad_slot_and_bad_image_are_refused(img, tmp_path):
    c = _approved(img)
    with pytest.raises(IdentityError, match="Unknown view slot"):
        set_view(c, "top", img)
    bad = tmp_path / "not_an_image.png"
    bad.write_text("hello")
    with pytest.raises(IdentityError, match="Not a readable image"):
        set_view(c, "side", bad)
    with pytest.raises(IdentityError, match="not found"):
        set_view(c, "side", tmp_path / "missing.png")


def test_front_is_the_approved_design_and_cannot_be_cleared(img):
    c = _approved(img)
    assert view_path(c, "front") == img
    with pytest.raises(IdentityError, match="front view"):
        clear_view(c, "front")
    c = clear_view(set_view(c, expression_slot("anger"), img), expression_slot("anger"))
    assert view_path(c, expression_slot("anger")) is None
    assert len(missing_slots(c)) == len(ALL_SLOTS) - 1


def test_views_do_not_carry_over_to_a_newly_approved_design(img):
    c = set_view(_approved(img), "side", img)
    c = add_candidates(c, [Candidate(id="k2", image_path=img, source=CandidateSource.UPLOADED)])
    c = approve_candidate(c, "k2")
    assert view_path(c, "side") is None              # new design, new views
    assert c.previous_approvals[-1].views["side"] == img


def test_sheet_reports_filled_and_empty_slots(img, tmp_path):
    c = set_view(_approved(img), expression_slot("sadness"), img)
    rep = render_sheet(c, tmp_path / "sheet.png", "The Last Silence")
    assert rep.approved and rep.version == 1
    assert rep.filled == ["front", "expression:sadness"]
    assert "side" in rep.missing and len(rep.missing) == len(ALL_SLOTS) - 2
    assert len(rep.palette) >= 2 and all(h.startswith("#") for h in rep.palette)
    assert "approved but not locked" in rep.warnings[0]
    with Image.open(tmp_path / "sheet.png") as im:
        assert im.size == (W, H)


def test_unapproved_character_gets_a_draft_sheet_without_a_hero(img, tmp_path):
    c = create_character("c1", "Elaine")
    c = add_candidates(c, [Candidate(id="k1", image_path=img, source=CandidateSource.UPLOADED)])
    rep = render_sheet(c, tmp_path / "draft.png")
    assert not rep.approved and rep.filled == [] and rep.palette == []
    assert "draft sheet" in rep.warnings[0]
    # The red DRAFT stamp is drawn in the bottom-right corner.
    with Image.open(tmp_path / "draft.png") as im:
        reds = sum(1 for x in range(W - 680, W - 40, 4) for y in range(H - 100, H - 40, 4)
                   if im.getpixel((x, y))[0] > 150 and im.getpixel((x, y))[1] < 90)
    assert reds > 50


def test_rendering_is_deterministic(img, tmp_path):
    c = lock_identity(_approved(img))
    a = render_sheet(c, tmp_path / "a.png")
    b = render_sheet(c, tmp_path / "b.png")
    digest = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
    assert digest(a.path) == digest(b.path)
