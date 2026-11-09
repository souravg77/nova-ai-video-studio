"""Script breakdown into characters, dialogue and shots; schema v3 storage."""
import json

import pytest

from nova_studio.director.breakdown import (BreakdownError, apply_breakdown,
                                            dialogue_seconds)
from nova_studio.director.model import DirectionSource, ShotKind
from nova_studio.director.parser import parse_script
from nova_studio.models.project import Project
from nova_studio.performance.characters import create_character
from nova_studio.performance.planner import DialogueLine, Shot
from nova_studio.storage.migrations import PROJECT_SCHEMA_VERSION
from nova_studio.storage.sqlite_store import ProjectStore, project_from_manifest

SCRIPT = """INT. KITCHEN - NIGHT

Ava waits by the window.

AVA
You came back!

BEN
(beat)
I promised I would.

EXT. GARDEN - DAWN

BEN
Look at the sky.
"""


def _breakdown(project=None, text=SCRIPT, **kw):
    project = project or Project(name="Test film")
    summary = apply_breakdown(project, parse_script(text), text, **kw)
    return project, summary


def test_new_characters_are_created_unapproved():
    p, s = _breakdown()
    assert s.new_characters == ["Ava", "Ben"]
    for c in p.characters:
        assert c.approved is None and not c.locked
        assert c.history[0].action == "created"


def test_existing_character_is_reused_untouched():
    p = Project()
    ben = create_character("char_ben", "Ben")
    ben.locked = True
    p.put_character(ben)
    before = ben.model_dump()
    p, s = _breakdown(p)
    assert s.reused_characters == ["Ben"] and s.new_characters == ["Ava"]
    assert p.character("char_ben").model_dump() == before
    assert {d.speaker_id for d in p.dialogue if d.text.startswith("Look")} == {"char_ben"}


def test_dialogue_shots_and_direction_link_up():
    p, s = _breakdown()
    assert [d.text for d in p.dialogue] == [
        "You came back!", "I promised I would.", "Look at the sky."]
    assert [d.order for d in p.dialogue] == [0, 1, 2]
    kinds = [p.director.shot_note(sh.id).kind for sh in p.shots]
    assert kinds == [ShotKind.ESTABLISHING, ShotKind.ACTION, ShotKind.DIALOGUE,
                     ShotKind.DIALOGUE, ShotKind.ESTABLISHING, ShotKind.DIALOGUE]
    for sh in p.shots:
        for lid in sh.dialogue_line_ids:
            line = next(d for d in p.dialogue if d.id == lid)
            assert sh.character_ids == [line.speaker_id]
    ava = next(c for c in p.characters if c.name == "Ava")
    action = p.shots[1]
    assert action.character_ids == [ava.id]          # named in the action line
    beat = p.director.line(p.dialogue[1].id)
    assert beat.parenthetical == "(beat)" and beat.source == DirectionSource.SCRIPT
    assert not beat.approved and beat.emotion is None
    assert [sc.location for sc in p.director.scenes] == ["KITCHEN", "GARDEN"]
    assert s.lines == 3 and s.shots == 6 and s.scenes == 2
    assert s.running_time_s == pytest.approx(sum(sh.duration_s for sh in p.shots))


def test_duration_estimates():
    assert dialogue_seconds("Hi.") == 1.5                       # minimum
    assert dialogue_seconds("one two three four five") == 2.6   # 5/2.5 + 0.6
    assert dialogue_seconds("one two three four five", "(beat)") == 3.6


def test_rerun_replaces_only_its_own_work():
    p, _ = _breakdown()
    first_ids = {d.id for d in p.dialogue}
    p, s = _breakdown(p, SCRIPT.replace("Look at the sky.", "Look up."))
    assert {d.id for d in p.dialogue}.isdisjoint(first_ids)
    assert p.dialogue[-1].text == "Look up."
    assert s.new_characters == [] and len(p.characters) == 2


def test_foreign_work_is_not_overwritten_without_confirmation():
    p = Project()
    p.dialogue.append(DialogueLine(id="mine", order=0, speaker_id="x", text="Hand-made"))
    p.shots.append(Shot(id="myshot", duration_s=2.0))
    with pytest.raises(BreakdownError, match="not made from the script"):
        _breakdown(p)
    assert [d.id for d in p.dialogue] == ["mine"] and p.characters == []
    p, _ = _breakdown(p, replace_existing=True)
    assert "mine" not in {d.id for d in p.dialogue}


def test_approved_plan_blocks_a_new_breakdown():
    p, _ = _breakdown()
    p.director.plan_approved = True
    with pytest.raises(BreakdownError, match="approved"):
        _breakdown(p)


def test_empty_script_is_refused():
    with pytest.raises(BreakdownError, match="Nothing to break down"):
        _breakdown(text="   \n")


def test_v2_project_upgrades_to_v3_and_director_data_survives_storage(tmp_path):
    v2 = json.loads(Project(name="Old").model_dump_json())
    v2.pop("director")
    v2["schema_version"] = 2
    up = project_from_manifest(v2)
    assert up.schema_version == PROJECT_SCHEMA_VERSION == 3
    assert up.director.script_text == "" and up.director.lines == []

    p, _ = _breakdown()
    with ProjectStore(tmp_path / "db.sqlite3") as store:
        store.save_project(p)
        back = store.load_project(p.id)
    assert back.director.script_text == SCRIPT
    assert back.director == p.director
    assert [d.text for d in back.dialogue] == [d.text for d in p.dialogue]
