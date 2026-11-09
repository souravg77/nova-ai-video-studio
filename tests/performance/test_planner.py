"""Shot planner: every spoken line is a performance; gaps are reported, never faked."""
from nova_studio.performance.characters import (
    Candidate, CandidateSource, add_candidates, approve_candidate,
    create_character, lock_identity)
from nova_studio.performance.engines import (
    ANY_LANGUAGE, EngineCapabilities, EngineRegistry, EngineSpec, EngineStatus,
    IdentityPreservation, Role)
from nova_studio.performance.planner import (
    DialogueLine, EngineSelection, Operation, PlanContext, ReferencePin, Route,
    Severity, Shot, plan_shot)

UP = lambda: EngineStatus(True)  # noqa: E731


def _char(cid, name):
    c = add_candidates(create_character(cid, name), [
        Candidate(id=f"{cid}-1", image_path="/x.png", source=CandidateSource.UPLOADED)])
    c = lock_identity(approve_candidate(c, f"{cid}-1"))
    return c.model_copy(update={"voice": c.voice.model_copy(update={"voice_id": "v1"})})


def _video(native=True, multi=False, langs=("en",), status=UP, max_d=10.0):
    return EngineSpec("vid", "TestVideo", frozenset({Role.VIDEO}), EngineCapabilities(
        video_generation=True, native_audio=native, multi_speaker_in_one_shot=multi,
        max_reference_images=3, identity_preservation=IdentityPreservation.REFERENCE_GUIDED,
        start_end_frames=True, min_duration_s=3, max_duration_s=max_d,
        aspect_ratios=("16:9", "9:16"), languages=langs), status_fn=status)


VOICE = EngineSpec("voice", "TestVoice", frozenset({Role.VOICE}), EngineCapabilities(
    speech_synthesis=True, languages=ANY_LANGUAGE), status_fn=UP)
LIPSYNC = EngineSpec("lips", "TestLips", frozenset({Role.LIPSYNC}), EngineCapabilities(
    lip_sync=True), status_fn=UP)


def _ctx(chars, lines, video="vid", voice=None, lipsync=None, lang="en"):
    return PlanContext(characters=chars, dialogue=lines, language=lang,
                       selection=EngineSelection(video=video, voice=voice, lipsync=lipsync))


MAYA, LEO = _char("maya", "Maya"), _char("leo", "Leo")
L1 = DialogueLine(id="l1", order=1, speaker_id="maya", text="Hi.")
L2 = DialogueLine(id="l2", order=2, speaker_id="leo", text="Hey.")


def codes(plan, sev=None):
    return {l.code for l in plan.limitations if sev is None or l.severity == sev}


def test_no_dialogue_is_video_only():
    p = plan_shot(Shot(id="s", duration_s=5, character_ids=["maya"]),
                  _ctx([MAYA], []), EngineRegistry([_video()]))
    assert p.route == Route.VIDEO_ONLY and p.can_proceed


def test_single_speaker_uses_native_audio_and_still_needs_validation():
    p = plan_shot(Shot(id="s", duration_s=6, character_ids=["maya"], dialogue_line_ids=["l1"]),
                  _ctx([MAYA], [L1]), EngineRegistry([_video()]))
    assert p.route == Route.NATIVE_AV and p.can_proceed
    assert p.steps[0].operation == Operation.GENERATE_VIDEO_WITH_AUDIO
    assert "validation" in codes(p)


def test_dialogue_without_capable_engines_is_blocked_not_faked():
    p = plan_shot(Shot(id="s", duration_s=6, character_ids=["maya"], dialogue_line_ids=["l1"]),
                  _ctx([MAYA], [L1]), EngineRegistry([_video(native=False)]))
    assert not p.can_proceed
    assert {"no_voice_engine", "no_lipsync_engine"} <= codes(p, Severity.BLOCKER)


def test_two_speakers_split_into_per_speaker_lipsync_passes():
    reg = EngineRegistry([_video(multi=False), VOICE, LIPSYNC])
    p = plan_shot(Shot(id="s", duration_s=8, character_ids=["maya", "leo"],
                       dialogue_line_ids=["l1", "l2"]),
                  _ctx([MAYA, LEO], [L1, L2], voice="voice", lipsync="lips"), reg)
    assert p.route == Route.SEPARATE_PERFORMANCE and p.can_proceed
    ops = [s.operation for s in p.steps]
    assert ops.count(Operation.LIP_SYNC) == 2 and Operation.COMPOSITE in ops


def test_unsupported_language_routes_to_separate_passes():
    reg = EngineRegistry([_video(langs=("en",)), VOICE, LIPSYNC])
    p = plan_shot(Shot(id="s", duration_s=6, character_ids=["maya"], dialogue_line_ids=["l1"]),
                  _ctx([MAYA], [L1], voice="voice", lipsync="lips", lang="hi"), reg)
    assert p.route == Route.SEPARATE_PERFORMANCE and "language" in codes(p)


def test_unapproved_character_blocks():
    raw = create_character("raw", "Raw")
    p = plan_shot(Shot(id="s", duration_s=5, character_ids=["raw"]),
                  _ctx([raw], []), EngineRegistry([_video()]))
    assert "character_not_approved" in codes(p, Severity.BLOCKER)


def test_unavailable_engine_and_too_long_shot_block():
    down = lambda: EngineStatus(False, "No API key")  # noqa: E731
    p = plan_shot(Shot(id="s", duration_s=12), _ctx([], []),
                  EngineRegistry([_video(status=down)]))
    blockers = codes(p, Severity.BLOCKER)
    assert {"video_engine_unavailable", "duration"} <= blockers
    assert any("No API key" in l.message for l in p.limitations)


def test_reapproved_character_warns_and_is_not_replaced():
    maya = MAYA
    shot = Shot(id="s", duration_s=5, character_ids=["maya"],
                pins=[ReferencePin(character_id="maya", reference_id="ref-old", version=1)])
    p = plan_shot(shot, _ctx([maya], []), EngineRegistry([_video()]))
    assert "reference_changed" in codes(p, Severity.WARNING)


def test_broken_status_check_reads_as_unavailable():
    def boom():
        raise RuntimeError("bad config")
    p = plan_shot(Shot(id="s", duration_s=5), _ctx([], []),
                  EngineRegistry([_video(status=boom)]))
    assert "video_engine_unavailable" in codes(p, Severity.BLOCKER)
