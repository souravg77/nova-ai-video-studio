"""Plan a shot against the selected engines and report every gap.

Every spoken line is a character performance. If the selected engines cannot
perform the dialogue, the plan says so and blocks; it never falls back to
laying audio over silent video.

Routes:
* ``native_av`` — one engine makes video and the spoken performance together.
* ``separate_performance`` — voice track first, base video, then a lip-sync
  pass per speaker (composited when several characters speak).
* ``video_only`` — the shot has no dialogue.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from .characters import Character, production_readiness
from .engines import EngineRegistry, EngineSpec, IdentityPreservation


class Route(str, Enum):
    NATIVE_AV = "native_av"
    SEPARATE_PERFORMANCE = "separate_performance"
    VIDEO_ONLY = "video_only"


class Severity(str, Enum):
    BLOCKER = "blocker"
    WARNING = "warning"
    INFO = "info"


class Limitation(BaseModel):
    severity: Severity
    code: str
    message: str


class Operation(str, Enum):
    SYNTHESIZE_SPEECH = "synthesize_speech"
    GENERATE_VIDEO = "generate_video"
    GENERATE_VIDEO_WITH_AUDIO = "generate_video_with_audio"
    LIP_SYNC = "lip_sync"
    COMPOSITE = "composite"


class PlanStep(BaseModel):
    engine_id: str
    operation: Operation
    description: str
    character_id: Optional[str] = None
    line_id: Optional[str] = None


class DialogueLine(BaseModel):
    id: str
    order: int
    speaker_id: str
    text: str


class ReferencePin(BaseModel):
    character_id: str
    reference_id: str
    version: int


class Shot(BaseModel):
    id: str
    duration_s: float
    character_ids: list[str] = Field(default_factory=list)
    dialogue_line_ids: list[str] = Field(default_factory=list)
    # The approved reference each character had when the shot was planned.
    pins: list[ReferencePin] = Field(default_factory=list)
    start_frame: Optional[str] = None
    end_frame: Optional[str] = None


class EngineSelection(BaseModel):
    video: Optional[str] = None
    voice: Optional[str] = None
    lipsync: Optional[str] = None


class PlanContext(BaseModel):
    characters: list[Character]
    dialogue: list[DialogueLine]
    selection: EngineSelection
    language: str = "en"
    aspect_ratio: str = "16:9"


class ShotPlan(BaseModel):
    shot_id: str
    route: Optional[Route]
    steps: list[PlanStep]
    limitations: list[Limitation]

    @property
    def blockers(self) -> list[Limitation]:
        return [x for x in self.limitations if x.severity == Severity.BLOCKER]

    @property
    def can_proceed(self) -> bool:
        return not self.blockers


def plan_shot(shot: Shot, ctx: PlanContext, registry: EngineRegistry) -> ShotPlan:
    lims: list[Limitation] = []
    steps: list[PlanStep] = []

    def add(sev: Severity, code: str, msg: str) -> None:
        lims.append(Limitation(severity=sev, code=code, message=msg))

    chars = {c.id: c for c in ctx.characters}

    # Characters must be approved; shots stay pinned to what they were planned with.
    for cid in shot.character_ids:
        c = chars.get(cid)
        if c is None:
            add(Severity.BLOCKER, "missing_character",
                f"Character {cid} no longer exists in the project.")
            continue
        r = production_readiness(c)
        if not r.ok:
            add(Severity.BLOCKER, "character_not_approved", r.reason)
            continue
        for w in r.warnings:
            add(Severity.WARNING, "character_readiness", w)
        pin = next((p for p in shot.pins if p.character_id == cid), None)
        if pin and pin.reference_id != r.reference_id:
            add(Severity.WARNING, "reference_changed",
                f"{c.name} was re-approved (now v{r.version}); this shot is "
                f"pinned to v{pin.version}. Re-pin it to use the new design. "
                f"Nothing is replaced automatically.")

    video = registry.get(ctx.selection.video)
    if video is None:
        add(Severity.BLOCKER, "no_video_engine", "No video engine selected.")
        return ShotPlan(shot_id=shot.id, route=None, steps=steps, limitations=lims)

    vs = video.status()
    vc = video.capabilities
    if not vs.available:
        add(Severity.BLOCKER, "video_engine_unavailable",
            f"{video.name} is unavailable: {vs.reason or 'unknown reason'}.")
    if not vc.video_generation:
        add(Severity.BLOCKER, "no_video_capability",
            f"{video.name} cannot generate video.")
    if vc.produces_placeholders:
        add(Severity.WARNING, "placeholder_engine",
            f"{video.name} produces placeholder takes only. They cannot pass "
            f"validation or be exported.")
    if vc.is_cloud:
        add(Severity.INFO, "cloud_engine",
            f"{video.name} runs in the cloud: prompts and reference images are "
            f"sent to the provider, and each generation is billed to your key.")
    if vc.video_generation:
        if shot.duration_s > vc.max_duration_s:
            add(Severity.BLOCKER, "duration",
                f"Shot is {shot.duration_s:.1f}s but {video.name} supports at "
                f"most {vc.max_duration_s:g}s. Split the shot or extend it in "
                f"a follow-up generation.")
        elif shot.duration_s < vc.min_duration_s:
            add(Severity.WARNING, "duration_short",
                f"Shot is {shot.duration_s:.1f}s; {video.name} makes at least "
                f"{vc.min_duration_s:g}s, so the take will be trimmed.")
        if vc.aspect_ratios and ctx.aspect_ratio not in vc.aspect_ratios:
            add(Severity.BLOCKER, "aspect_ratio",
                f"{video.name} does not support {ctx.aspect_ratio}.")
        if (shot.start_frame or shot.end_frame) and not vc.start_end_frames:
            add(Severity.BLOCKER, "start_end_frames",
                f"{video.name} cannot start or end on a chosen frame.")
        n = len(shot.character_ids)
        if n and n > vc.max_reference_images:
            add(Severity.WARNING, "reference_count",
                f"{n} characters but {video.name} accepts "
                f"{vc.max_reference_images} reference image(s).")
        if n:
            if vc.identity_preservation in (IdentityPreservation.NONE,
                                            IdentityPreservation.WEAK):
                word = "no" if vc.identity_preservation == IdentityPreservation.NONE else "weak"
                add(Severity.WARNING, "identity",
                    f"{video.name} has {word} identity preservation. Characters "
                    f"may not match their approved design; review every take.")
            elif vc.identity_preservation == IdentityPreservation.REFERENCE_GUIDED:
                add(Severity.INFO, "identity",
                    "Identity is guided by approved reference images. This is "
                    "not a trained identity model.")

    lines_by_id = {l.id: l for l in ctx.dialogue}
    lines = [lines_by_id[i] for i in shot.dialogue_line_ids if i in lines_by_id]
    speakers = list(dict.fromkeys(l.speaker_id for l in lines))

    def done(route: Route) -> ShotPlan:
        return ShotPlan(shot_id=shot.id, route=route, steps=steps, limitations=lims)

    if not lines:
        steps.append(PlanStep(engine_id=video.id, operation=Operation.GENERATE_VIDEO,
                              description="Generate the shot (no dialogue)."))
        return done(Route.VIDEO_ONLY)

    native_ok = (vs.available and vc.native_audio
                 and (len(speakers) <= 1 or vc.multi_speaker_in_one_shot)
                 and vc.supports_language(ctx.language))
    if native_ok:
        steps.append(PlanStep(
            engine_id=video.id, operation=Operation.GENERATE_VIDEO_WITH_AUDIO,
            description=f"Generate video with {len(lines)} spoken line(s) and "
                        f"synchronised performance."))
        if not vc.emotion_control:
            add(Severity.WARNING, "emotion_control",
                f"{video.name} has no explicit emotion control; emotion "
                f"direction is passed as prompt text only.")
        add(Severity.INFO, "validation",
            "The take still has to pass lip-sync validation before the shot "
            "can be approved.")
        return done(Route.NATIVE_AV)

    if vc.native_audio and len(speakers) > 1 and not vc.multi_speaker_in_one_shot:
        add(Severity.INFO, "multi_speaker",
            f"{video.name} cannot reliably perform {len(speakers)} speakers in "
            f"one generation; using separate performance passes.")
    elif vc.native_audio and not vc.supports_language(ctx.language):
        add(Severity.INFO, "language",
            f"{video.name} does not list '{ctx.language}' as supported; using "
            f"separate voice and lip-sync passes.")

    voice = registry.get(ctx.selection.voice)
    lipsync = registry.get(ctx.selection.lipsync)
    _check_voice(voice, ctx.language, add)
    _check_lipsync(lipsync, add)

    for l in lines:
        c = chars.get(l.speaker_id)
        if c is not None and not c.voice.voice_id:
            add(Severity.WARNING, "voice_profile",
                f"{c.name} has no voice assigned in their profile yet.")
        steps.append(PlanStep(
            engine_id=voice.id if voice else "-", operation=Operation.SYNTHESIZE_SPEECH,
            character_id=l.speaker_id, line_id=l.id,
            description=f"Voice line {l.order} ({c.name if c else l.speaker_id})."))
    steps.append(PlanStep(engine_id=video.id, operation=Operation.GENERATE_VIDEO,
                          description="Generate the base performance video."))
    for sp in speakers:
        c = chars.get(sp)
        steps.append(PlanStep(
            engine_id=lipsync.id if lipsync else "-", operation=Operation.LIP_SYNC,
            character_id=sp,
            description=f"Lip-sync pass for {c.name if c else sp} on their own lines only."))
    if len(speakers) > 1:
        steps.append(PlanStep(engine_id="nova", operation=Operation.COMPOSITE,
                              description="Composite the per-speaker passes so each "
                                          "mouth moves only on its own lines."))
        add(Severity.WARNING, "composite",
            "Multi-speaker shots are built from separate passes. Check the "
            "edges where passes are combined.")
    return done(Route.SEPARATE_PERFORMANCE)


def _check_voice(voice: Optional[EngineSpec], lang: str, add) -> None:
    if voice is None:
        add(Severity.BLOCKER, "no_voice_engine",
            "Dialogue needs a voice engine, and none is selected.")
        return
    s = voice.status()
    if not s.available:
        add(Severity.BLOCKER, "voice_engine_unavailable",
            f"{voice.name} is unavailable: {s.reason or 'unknown reason'}.")
    elif not voice.capabilities.speech_synthesis:
        add(Severity.BLOCKER, "no_speech", f"{voice.name} cannot synthesise speech.")
    elif not voice.capabilities.supports_language(lang):
        add(Severity.BLOCKER, "voice_language", f"{voice.name} does not support '{lang}'.")


def _check_lipsync(lipsync: Optional[EngineSpec], add) -> None:
    if lipsync is None:
        add(Severity.BLOCKER, "no_lipsync_engine",
            "Dialogue needs a lip-sync engine so mouth movement matches the "
            "audio, and none is selected. NOVA will not fake a spoken performance.")
        return
    s = lipsync.status()
    if not s.available:
        add(Severity.BLOCKER, "lipsync_engine_unavailable",
            f"{lipsync.name} is unavailable: {s.reason or 'unknown reason'}.")
    elif not lipsync.capabilities.lip_sync:
        add(Severity.BLOCKER, "no_lipsync", f"{lipsync.name} cannot lip-sync.")
    else:
        if not lipsync.capabilities.emotion_control:
            add(Severity.WARNING, "lipsync_emotion",
                f"{lipsync.name} syncs the mouth only; facial emotion comes "
                f"from the base video.")
        if not lipsync.capabilities.head_motion_control:
            add(Severity.WARNING, "lipsync_head", f"{lipsync.name} has no head-motion control.")


def pin_shot(shot: Shot, characters: list[Character]) -> Shot:
    """Pin each approved character in the shot to their current reference.

    Only an explicit call re-pins; a later re-approval never changes a shot
    on its own (the planner warns instead).
    """
    by_id = {c.id: c for c in characters}
    pins = []
    for cid in shot.character_ids:
        c = by_id.get(cid)
        if c is not None and c.approved:
            pins.append(ReferencePin(character_id=cid,
                                     reference_id=c.approved.reference_id,
                                     version=c.approved.version))
    return shot.model_copy(update={"pins": pins})
