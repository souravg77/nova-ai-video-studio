"""Three-photo intake validation."""
import pytest

from nova_studio.phase4.intake import (approve_identity, intake_photos,
                                       validate_photo)

pytestmark = pytest.mark.export  # fixtures need ffmpeg to make images


def test_tiny_image_rejected(photos):
    v = validate_photo(photos["tiny"])
    assert v.ok is False
    assert any("Resolution" in r for r in v.reasons)


def test_dark_image_rejected(photos):
    v = validate_photo(photos["dark"])
    assert v.ok is False
    assert any("too dark" in r for r in v.reasons)


def test_missing_file_rejected(tmp_path):
    v = validate_photo(tmp_path / "nope.png")
    assert v.ok is False
    assert any("missing" in r.lower() for r in v.reasons)


def test_face_detection_unavailable_is_warning_not_pass(photos):
    # In CI the Haar cascade is absent -> faces_detected None + warning, and
    # the photo is NOT auto-failed on face grounds (size/brightness ok).
    v = validate_photo(photos["good"][0])
    if v.faces_detected is None:
        assert any("detection unavailable" in w.lower() for w in v.warnings)


def test_approval_blocked_until_three_usable(photos):
    # Mix: 2 good + 1 tiny -> not all usable -> approval blocked.
    res = intake_photos([photos["good"][0], photos["good"][1], photos["tiny"]])
    assert res.all_usable is False
    with pytest.raises(ValueError):
        approve_identity(res)


def test_requires_exactly_three(photos):
    res = intake_photos([photos["good"][0], photos["good"][1]])
    # Only two -> all_usable is False (needs exactly three).
    assert res.all_usable is False
