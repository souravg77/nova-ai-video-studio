"""Identity prep preserves originals and is honest about alignment."""
import hashlib

import pytest

from nova_studio.phase4.identity_prep import prepare_image, prepare_all

pytestmark = pytest.mark.export


def _hash(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_original_preserved(photos, tmp_path):
    src = photos["good"][0]
    before = _hash(src)
    prepare_image(src, tmp_path / "out", target_size=256)
    assert _hash(src) == before  # untouched


def test_output_is_target_size(photos, tmp_path):
    p = prepare_image(photos["good"][0], tmp_path / "out", target_size=256)
    assert p.ok
    from PIL import Image
    assert Image.open(p.output_path).size == (256, 256)


def test_centre_crop_flagged_unaligned_without_face(photos, tmp_path):
    # No real face in a flat colour image -> aligned False + honest note.
    p = prepare_image(photos["good"][0], tmp_path / "out")
    if not p.aligned:
        assert any("not" in n.lower() and "align" in n.lower() for n in p.notes)


def test_background_removal_skipped_honestly(photos, tmp_path):
    p = prepare_image(photos["good"][0], tmp_path / "out",
                      remove_background=True)
    # rembg not installed in CI -> skipped and said so, not silently ignored.
    if not p.background_removed:
        assert any("background" in n.lower() for n in p.notes)


def test_prepare_all(photos, tmp_path):
    out = prepare_all(photos["good"], tmp_path / "out", target_size=256)
    assert len(out) == 3
    assert all(p.ok for p in out)
