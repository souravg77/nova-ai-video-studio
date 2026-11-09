"""Deterministic script parsing: Fountain screenplays and plain 'Name: line'."""
from nova_studio.director.parser import ElementKind, display_name, parse_script

FOUNTAIN = """Title:
    _The Last Silence_
Author: Shawn
Draft date: 9 Nov 2026

INT. GRAND HALL - NIGHT

Elaine stands alone. A gramophone plays.

ARTHUR (O.S.)
Elaine? You came back!

ELAINE
(quietly)
I promised I would.
(beat)
I always keep my promises.

THE DOOR SLAMS.
Rain hammers the windows.

ARTHUR (CONT'D)
Then stay. /* cut this joke? */ Please.

CUT TO:

.FLASHBACK - THE PIER

@McAllister
Morning, both of you. [[check spelling]]

BRENDA ^
Morning.

> FADE OUT.
"""


def test_title_page_and_format():
    p = parse_script(FOUNTAIN)
    assert p.title == "The Last Silence"
    assert p.format == "fountain"
    assert p.warnings == []


def test_scene_headings_with_location_and_time():
    p = parse_script(FOUNTAIN)
    assert [(s.int_ext, s.location, s.time_of_day) for s in p.scenes] == [
        ("INT", "GRAND HALL", "NIGHT"), ("", "FLASHBACK - THE PIER", "")]
    assert not any(s.implicit for s in p.scenes)


def test_dialogue_speakers_parentheticals_and_extensions():
    p = parse_script(FOUNTAIN)
    d = [(e.speaker, e.parenthetical, e.extension, e.text) for e in p.dialogue]
    assert d == [
        ("Arthur", "", "O.S.", "Elaine? You came back!"),
        ("Elaine", "(quietly)", "", "I promised I would."),
        ("Elaine", "(beat)", "", "I always keep my promises."),
        ("Arthur", "", "", "Then stay. Please."),          # CONT'D dropped, boneyard removed
        ("McAllister", "", "", "Morning, both of you."),   # forced cue, note removed
        ("Brenda", "", "", "Morning."),
    ]
    assert p.dialogue[-1].dual is True
    assert p.speakers == ["Arthur", "Elaine", "McAllister", "Brenda"]


def test_capitalised_sentence_is_action_not_a_speaker():
    p = parse_script(FOUNTAIN)
    actions = [e.text for e in p.elements if e.kind == ElementKind.ACTION]
    assert "THE DOOR SLAMS. Rain hammers the windows." in actions
    assert "The Door Slams" not in p.speakers


def test_transitions():
    p = parse_script(FOUNTAIN)
    assert [e.text for e in p.elements if e.kind == ElementKind.TRANSITION] == [
        "CUT TO:", "FADE OUT."]


def test_plain_name_colon_script():
    p = parse_script("Ava: Hello there.\nBen (V.O.): (nervous) Hi.\n\nAva: Shall we go?\n")
    assert p.format == "plain"
    assert [(e.speaker, e.parenthetical, e.extension, e.text) for e in p.dialogue] == [
        ("Ava", "", "", "Hello there."), ("Ben", "(nervous)", "V.O.", "Hi."),
        ("Ava", "", "", "Shall we go?")]
    assert len(p.scenes) == 1 and p.scenes[0].implicit
    assert any("No scene headings" in w for w in p.warnings)


def test_action_before_first_heading_gets_an_implicit_opening_scene():
    p = parse_script("Black screen. A heartbeat.\n\nEXT. FIELD - DAY\n\nWind.\n")
    assert [s.implicit for s in p.scenes] == [True, False]
    assert [e.scene_index for e in p.elements] == [0, 1]


def test_empty_and_dialogue_free_scripts_are_reported():
    assert "The script is empty." in parse_script("  \n\n").warnings
    p = parse_script("INT. ROOM - DAY\n\nNobody speaks.\n")
    assert any("No dialogue found" in w for w in p.warnings)


def test_same_input_same_output():
    a, b = parse_script(FOUNTAIN), parse_script(FOUNTAIN)
    assert [(e.kind, e.text, e.speaker) for e in a.elements] == \
           [(e.kind, e.text, e.speaker) for e in b.elements]


def test_display_name():
    assert display_name("ELAINE  VANCE") == "Elaine Vance"
    assert display_name("HENRY VIII") == "Henry VIII"
    assert display_name("McAllister") == "McAllister"
