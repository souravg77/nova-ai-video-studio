"""Project-wide undo/redo and autosave bookkeeping."""
from nova_studio.core.history import ProjectHistory, fingerprint
from nova_studio.director.breakdown import apply_breakdown
from nova_studio.director.parser import parse_script
from nova_studio.models.project import Project, Scene

SCRIPT = "INT. HALL - NIGHT\n\nAVA\nHello.\n"


def test_idle_polling_records_nothing():
    p = Project(name="A")
    h = ProjectHistory(p)
    assert not h.record() and not h.record()
    assert not h.can_undo
    p.touch()                                   # timestamps alone are not edits
    assert not h.record()


def test_undo_and_redo_restore_in_place():
    p = Project(name="A")
    h = ProjectHistory(p)
    same = p
    p.name = "B"
    h.record()
    apply_breakdown(p, parse_script(SCRIPT), SCRIPT)
    h.record()
    assert h.undo() and p is same
    assert p.name == "B" and p.dialogue == [] and p.director.script_text == ""
    assert h.undo() and p.name == "A"
    assert not h.undo()
    assert h.redo() and p.name == "B"
    assert h.redo() and p.director.script_text == SCRIPT and len(p.characters) == 1
    assert not h.redo()


def test_undo_keeps_an_unrecorded_edit_redoable():
    p = Project(name="A")
    h = ProjectHistory(p)
    p.add_scene(Scene(title="New"))             # not yet recorded by a poll
    assert h.undo() and p.scenes == []
    assert h.redo() and [s.title for s in p.scenes] == ["New"]


def test_a_new_edit_clears_redo():
    p = Project(name="A")
    h = ProjectHistory(p)
    p.name = "B"
    h.record()
    h.undo()
    p.name = "C"
    h.record()
    assert not h.can_redo and p.name == "C"


def test_history_is_bounded():
    p = Project(name="0")
    h = ProjectHistory(p, limit=3)
    for i in range(1, 10):
        p.name = str(i)
        h.record()
    steps = 0
    while h.undo():
        steps += 1
    assert steps == 3 and p.name == "6"


def test_dirty_tracks_saves():
    p = Project(name="A")
    h = ProjectHistory(p)
    assert h.dirty                              # never saved
    h.mark_saved()
    assert not h.dirty
    p.name = "B"
    assert h.dirty
    h.mark_saved()
    assert not h.dirty and fingerprint(p) == h.saved_hash
