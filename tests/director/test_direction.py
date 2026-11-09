"""Line direction: script readings, model suggestions, approval rules."""
import json
import os
from pathlib import Path

import pytest

from nova_studio.director.breakdown import apply_breakdown
from nova_studio.director.direction import (
    EMOTIONS, approve_line, approve_plan, approved_direction,
    from_parenthetical, parse_reply, set_direction, suggest_directions,
    unapprove_plan)
from nova_studio.director.model import DirectionSource
from nova_studio.director.parser import parse_script
from nova_studio.models.project import Project

SCRIPT = """INT. HALL - NIGHT

ARTHUR
Elaine? You came back!

ELAINE
(quietly)
I promised I would.

ARTHUR
(angrily)
Then why did you leave?

ELAINE
Because I had to.
"""


def _project():
    p = Project()
    apply_breakdown(p, parse_script(SCRIPT), SCRIPT)
    return p


def _lines(p):
    return [p.director.line(d.id) for d in p.dialogue]


def _fake(answers):
    """A fake model that answers each prompt line in order; records prompts."""
    calls = []

    def complete(system, user):
        calls.append(user)
        n = sum(1 for ln in user.splitlines() if ln[:1].isdigit())
        return json.dumps({"lines": [dict(n=i + 1, **answers[i % len(answers)])
                                     for i in range(n)]})
    complete.calls = calls
    return complete


def test_parentheticals_are_read_deterministically():
    assert from_parenthetical("(angrily)")[:3] == ("anger", "moderate", None)
    assert from_parenthetical("(quietly)")[:3] == (None, "subtle", "slow")
    assert from_parenthetical("(sobbing, quietly)")[:3] == ("sadness", "strong", "slow")
    assert from_parenthetical("(to Ben)") is None
    assert from_parenthetical("") is None


def test_breakdown_applies_script_directions_unapproved():
    p = _project()
    arthur1, elaine1, arthur2, elaine2 = _lines(p)
    assert arthur2.source == DirectionSource.SCRIPT and arthur2.emotion == "anger"
    assert elaine1.source == DirectionSource.SCRIPT and elaine1.pace == "slow"
    assert arthur1.source is None and elaine2.source is None
    assert not any(d.approved for d in _lines(p))


def test_model_fills_gaps_but_never_overrides_the_writer():
    p = _project()
    fake = _fake([{"emotion": "sadness", "intensity": "strong", "pace": "fast"}])
    rep = suggest_directions(p, fake)
    arthur1, elaine1, arthur2, elaine2 = _lines(p)
    assert rep.suggested == 3 and rep.kept_script == 1 and rep.rejected == []
    assert (arthur2.emotion, arthur2.intensity) == ("anger", "moderate")   # writer wins
    assert arthur2.source == DirectionSource.SCRIPT
    # "(quietly)" keeps subtle/slow; only the missing emotion is suggested.
    assert (elaine1.emotion, elaine1.intensity, elaine1.pace) == ("sadness", "subtle", "slow")
    assert "emotion suggested" in elaine1.note
    assert arthur1.source == DirectionSource.SUGGESTED and not arthur1.approved
    # The prompt carries scene, speaker and the writer's parenthetical.
    assert "[Scene: INT. HALL - NIGHT]" in fake.calls[0]
    assert "Elaine (quietly): I promised I would." in fake.calls[0]


def test_user_choices_and_approved_lines_are_never_touched():
    p = _project()
    a1, e1, a2, e2 = p.dialogue
    set_direction(p, a1.id, "happiness", "strong", "fast")
    approve_line(p, e2.id)
    suggest_directions(p, _fake([{"emotion": "fear", "intensity": "subtle", "pace": "slow"}]))
    assert p.director.line(a1.id).emotion == "happiness"
    assert p.director.line(a1.id).source == DirectionSource.USER
    assert p.director.line(e2.id).emotion is None and p.director.line(e2.id).approved


def test_invalid_model_answers_are_rejected_not_stored():
    got, problems = parse_reply(json.dumps({"lines": [
        {"n": 1, "emotion": "joy", "intensity": "moderate", "pace": "normal"},
        {"n": 2, "emotion": "anger", "intensity": "huge", "pace": "normal"},
        {"n": 9, "emotion": "anger", "intensity": "subtle", "pace": "normal"},
        {"n": 3, "emotion": "anger", "intensity": "subtle", "pace": "fast"}]}), 3)
    assert got == {3: ("anger", "subtle", "fast")}
    assert len(problems) == 3
    assert parse_reply("I think they are sad.", 2) == ({}, ["no JSON in the model's reply"])
    # Bare arrays from unconstrained models are accepted too.
    got, _ = parse_reply('[{"n": 1, "emotion": "fear", "intensity": "strong", "pace": "fast"}]', 1)
    assert got == {1: ("fear", "strong", "fast")}


def test_set_direction_validates_vocabulary():
    p = _project()
    with pytest.raises(ValueError, match="unknown emotion"):
        set_direction(p, p.dialogue[0].id, "joy", None, None)


def test_plan_approval_requires_every_line_and_blocks_rebreakdown():
    p = _project()
    with pytest.raises(ValueError, match="4 line"):
        approve_plan(p)
    for d in p.dialogue:
        approve_line(p, d.id)
    approve_plan(p)
    assert p.director.plan_approved
    unapprove_plan(p)
    assert not p.director.plan_approved


def test_only_approved_direction_is_exposed_to_other_modules():
    p = _project()
    a2 = p.dialogue[2]
    assert approved_direction(p, a2.id) is None          # script reading, unapproved
    approve_line(p, a2.id)
    d = approved_direction(p, a2.id)
    assert (d.emotion, d.intensity) == ("anger", "moderate")
    assert approved_direction(p, "missing") is None


def test_vocabulary_has_the_six_basic_emotions():
    for e in ("neutral", "happiness", "sadness", "surprise", "fear", "disgust", "anger"):
        assert e in EMOTIONS


MODEL = Path(os.environ.get("LOCALAPPDATA", "")) / "NovaStudio" / "NovaStudio" / \
    "models" / "script" / "qwen2.5-1.5b-instruct-q4_k_m.gguf"


@pytest.mark.skipif(not MODEL.exists(), reason="local Qwen model not installed")
def test_real_local_model_gives_valid_suggestions():
    pytest.importorskip("llama_cpp")
    from nova_studio.director.direction import llama_complete
    p = _project()
    rep = suggest_directions(p, llama_complete(str(MODEL)))
    assert rep.rejected == []
    assert rep.suggested == 3
    for d in _lines(p):
        assert d.emotion in EMOTIONS
