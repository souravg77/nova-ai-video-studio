"""Location references: created by the breakdown, approved as a set, used as frames."""
import subprocess

import pytest
from PIL import Image

from nova_studio.director.animatic import build_animatic
from nova_studio.director.breakdown import apply_breakdown
from nova_studio.director.model import LocationRef
from nova_studio.director.parser import parse_script
from nova_studio.media.probe import ffmpeg_path
from nova_studio.media.renderer import Renderer
from nova_studio.models.project import Project
from nova_studio.sheets.compose import H, W, render_location_sheet
from nova_studio.sheets.locations import (
    LocationError, approve_location, approved_frame, clear_location_view,
    put_location, set_location_view, unapprove_location)

SCRIPT = """INT. GRAND HALL - NIGHT

Rain on the windows.

EXT. GARDEN - DAWN

Birds.

INT. GRAND HALL - LATER

Silence.
"""


@pytest.fixture
def img(tmp_path):
    p = tmp_path / "hall.png"
    Image.new("RGB", (320, 200), (120, 90, 60)).save(p)
    return str(p)


def test_breakdown_creates_one_unapproved_location_per_place():
    p = Project()
    s = apply_breakdown(p, parse_script(SCRIPT), SCRIPT)
    assert [l.name for l in p.director.locations] == ["GRAND HALL", "GARDEN"]
    assert s.new_locations == ["GRAND HALL", "GARDEN"]
    assert not any(l.approved for l in p.director.locations)
    assert p.director.location_for_scene(2).name == "GRAND HALL"


def test_rebreakdown_keeps_existing_locations_and_their_views(img):
    p = Project()
    apply_breakdown(p, parse_script(SCRIPT), SCRIPT)
    hall = approve_location(set_location_view(p.director.locations[0], "front", img))
    put_location(p.director, hall)
    s = apply_breakdown(p, parse_script(SCRIPT), SCRIPT)
    assert s.new_locations == []
    assert p.director.location_named("grand hall").approved
    assert p.director.location_named("GRAND HALL").views["front"] == img


def test_approval_rules(img, tmp_path):
    loc = LocationRef(id="l1", name="HALL")
    with pytest.raises(LocationError, match="frontal view"):
        approve_location(loc)
    with pytest.raises(LocationError, match="Unknown location slot"):
        set_location_view(loc, "ceiling", img)
    bad = tmp_path / "bad.png"
    bad.write_text("x")
    with pytest.raises(LocationError, match="Not a readable image"):
        set_location_view(loc, "front", bad)

    loc = approve_location(set_location_view(loc, "front", img))
    assert loc.approved and loc.version == 1 and loc.approved_at
    with pytest.raises(LocationError, match="Unapprove"):
        set_location_view(loc, "left", img)
    with pytest.raises(LocationError, match="Unapprove"):
        clear_location_view(loc, "front")
    loc = approve_location(set_location_view(unapprove_location(loc), "left", img))
    assert loc.version == 2


def test_only_an_approved_location_gives_a_frame(img):
    loc = set_location_view(LocationRef(id="l", name="HALL"), "front", img)
    assert approved_frame(loc) is None
    assert approved_frame(approve_location(loc)) == img
    assert approved_frame(None) is None


def test_location_sheet(img, tmp_path):
    loc = set_location_view(LocationRef(id="l", name="HALL"), "front", img)
    draft = render_location_sheet(loc, tmp_path / "d.png")
    assert not draft.approved and "draft sheet" in draft.warnings[0]
    rep = render_location_sheet(approve_location(loc), tmp_path / "a.png", ["INT. HALL - NIGHT"])
    assert rep.approved and rep.version == 1
    assert rep.filled == ["front"] and "reverse_wide" in rep.missing
    assert rep.palette
    with Image.open(tmp_path / "a.png") as im:
        assert im.size == (W, H)


@pytest.mark.ffmpeg
def test_animatic_uses_approved_location_for_shots_without_characters(tmp_path):
    p = Project(name="Loc")
    apply_breakdown(p, parse_script(SCRIPT), SCRIPT)
    png = tmp_path / "hall.png"
    subprocess.run([ffmpeg_path(), "-y", "-f", "lavfi", "-i", "color=c=brown:s=320x240:d=1",
                    "-frames:v", "1", str(png)], check=True, capture_output=True)
    put_location(p.director, approve_location(
        set_location_view(p.director.locations[0], "front", str(png))))
    rep = build_animatic(p, Renderer(), None, tmp_path / "a.mp4",
                         width=320, height=180, fps=12, preset="ultrafast")
    assert rep.ok, rep.message
    # Hall scenes (1 and 3): establishing + action each use the hall; garden stays cards.
    assert (rep.image_frames, rep.location_frames, rep.title_cards) == (0, 4, 2)
