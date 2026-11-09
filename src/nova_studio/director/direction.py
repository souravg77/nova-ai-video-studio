"""Emotion, intensity and pace for each dialogue line (roadmap M2, M4).

Three sources, never mixed up:
* SCRIPT    - read deterministically from the writer's parenthetical
              ("(angrily)" -> anger, strong);
* SUGGESTED - proposed by the local language model;
* USER      - chosen or confirmed by the user.
Nothing is used for production until it is approved. Suggestions never
overwrite an approved line or a user's choice.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from .model import DirectionSource, LineDirection

# Six basic emotions plus neutral, and named blends of them (roadmap 7b).
BASE_EMOTIONS = ("neutral", "happiness", "sadness", "surprise", "fear",
                 "disgust", "anger")
BLENDS = {
    "excited": ("happiness", "surprise"),
    "relieved": ("happiness", "sadness"),
    "tender": ("happiness",),
    "romantic": ("happiness",),
    "confident": ("happiness",),
    "nervous": ("fear",),
    "sarcastic": ("disgust", "happiness"),
    "determined": ("anger",),
    "shocked": ("surprise", "fear"),
    "grief": ("sadness",),
}
EMOTIONS = BASE_EMOTIONS + tuple(BLENDS)
INTENSITIES = ("subtle", "moderate", "strong")
PACES = ("slow", "normal", "fast")

# Parenthetical keyword -> (emotion, intensity, pace). Checked in order; the
# first match wins. Keys are matched as whole words, case-insensitively.
_PAREN_RULES: list[tuple[tuple[str, ...], tuple[Optional[str], Optional[str], Optional[str]]]] = [
    (("furious", "furiously", "enraged", "yelling", "shouting", "screaming"), ("anger", "strong", "fast")),
    (("angry", "angrily", "snapping", "snaps", "bitterly"), ("anger", "moderate", None)),
    (("terrified", "panicked", "panicking"), ("fear", "strong", "fast")),
    (("scared", "afraid", "frightened", "fearful"), ("fear", "moderate", None)),
    (("nervous", "nervously", "hesitant", "hesitantly", "stammering", "anxious"), ("nervous", "moderate", "slow")),
    (("sobbing", "crying", "weeping", "in tears"), ("sadness", "strong", "slow")),
    (("sad", "sadly", "sorrowful", "mournful", "softly sad", "grieving"), ("sadness", "moderate", "slow")),
    (("shocked", "stunned", "aghast"), ("shocked", "strong", None)),
    (("surprised", "astonished", "amazed"), ("surprise", "moderate", None)),
    (("disgusted", "revolted", "with disgust"), ("disgust", "moderate", None)),
    (("sarcastic", "sarcastically", "dryly", "wryly"), ("sarcastic", "subtle", None)),
    (("excited", "excitedly", "thrilled", "eagerly"), ("excited", "strong", "fast")),
    (("relieved", "with relief"), ("relieved", "moderate", None)),
    (("laughing", "happily", "delighted", "joyful", "beaming", "grinning", "smiling"), ("happiness", "moderate", None)),
    (("tenderly", "gently", "lovingly", "warmly"), ("tender", "subtle", "slow")),
    (("confident", "confidently", "firmly", "resolute"), ("confident", "moderate", None)),
    (("determined",), ("determined", "moderate", None)),
    (("quietly", "softly", "whispering", "whispers", "under her breath", "under his breath"), (None, "subtle", "slow")),
    (("beat", "pause", "a moment", "silence"), (None, None, "slow")),
    (("quickly", "rapidly", "rushed", "hurried"), (None, None, "fast")),
    (("flat", "flatly", "deadpan", "evenly"), ("neutral", "subtle", None)),
]


def _matches(paren: str, keys: tuple[str, ...]) -> Optional[str]:
    for k in keys:
        if re.search(rf"\b{re.escape(k)}\b", paren, re.I):
            return k
    return None


def from_parenthetical(paren: str) -> Optional[tuple[Optional[str], Optional[str], Optional[str], str]]:
    """Deterministic reading of the writer's direction, or None."""
    if not paren:
        return None
    emotion = intensity = pace = None
    hits = []
    for keys, (e, i, p) in _PAREN_RULES:
        k = _matches(paren, keys)
        if not k:
            continue
        hits.append(k)
        emotion = emotion or e
        intensity = intensity or i
        pace = pace or p
    if not hits:
        return None
    return emotion, intensity, pace, f"from {paren}"


def _editable(d: LineDirection) -> bool:
    return not d.approved and d.source != DirectionSource.USER


def apply_script_directions(director) -> int:
    """Fill unapproved lines from their parentheticals. Returns lines changed."""
    changed = 0
    for d in director.lines:
        if not _editable(d):
            continue
        got = from_parenthetical(d.parenthetical)
        if got is None:
            continue
        d.emotion, d.intensity, d.pace, d.note = got
        d.source = DirectionSource.SCRIPT
        changed += 1
    return changed


# ---- local model suggestions ------------------------------------------------

@dataclass
class SuggestionReport:
    suggested: int = 0
    kept_script: int = 0
    skipped_locked: int = 0
    rejected: list[str] = field(default_factory=list)   # invalid model answers
    unavailable: str = ""                               # why nothing ran


SYSTEM_PROMPT = (
    "You are a film director's assistant. For each numbered dialogue line, "
    "choose how the actor should deliver it. Reply with ONLY JSON: {\"lines\": "
    "[...]} with one object per line: {\"n\": <line number>, \"emotion\": <one of "
    + ", ".join(EMOTIONS) + ">, \"intensity\": <subtle|moderate|strong>, "
    "\"pace\": <slow|normal|fast>}. Use only those words. Do not explain.")


def build_prompt(project, line_ids: list[str]) -> str:
    names = {c.id: c.name for c in project.characters}
    scenes = {s.index: s for s in project.director.scenes}
    by_id = {d.id: d for d in project.dialogue}
    rows, last_scene = [], None
    for n, lid in enumerate(line_ids, start=1):
        d, dd = by_id[lid], project.director.line(lid)
        if dd and dd.scene_index != last_scene:
            sc = scenes.get(dd.scene_index)
            if sc and sc.heading:
                rows.append(f"[Scene: {sc.heading}]")
            last_scene = dd.scene_index
        paren = f" {dd.parenthetical}" if dd and dd.parenthetical else ""
        rows.append(f"{n}. {names.get(d.speaker_id, 'Unknown')}{paren}: {d.text}")
    return "\n".join(rows)


# JSON schema the local model is constrained to (llama.cpp grammar), so a
# small model cannot answer outside the vocabulary or with broken JSON.
REPLY_SCHEMA = {
    "type": "object",
    "properties": {"lines": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "n": {"type": "integer"},
            "emotion": {"type": "string", "enum": list(EMOTIONS)},
            "intensity": {"type": "string", "enum": list(INTENSITIES)},
            "pace": {"type": "string", "enum": list(PACES)},
        },
        "required": ["n", "emotion", "intensity", "pace"]}}},
    "required": ["lines"],
}


def parse_reply(text: str, count: int) -> tuple[dict[int, tuple[str, str, str]], list[str]]:
    """Strictly validate the model's JSON. Returns ({n: (e, i, p)}, problems).

    Accepts {"lines": [...]} (schema-constrained output) or a bare array.
    Every value is checked again here; the schema is not trusted blindly.
    """
    problems: list[str] = []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\[.*\]", text, re.S)
        if not m:
            return {}, ["no JSON in the model's reply"]
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError as exc:
            return {}, [f"unreadable JSON: {exc.msg}"]
    items = data.get("lines", []) if isinstance(data, dict) else data
    out: dict[int, tuple[str, str, str]] = {}
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        try:
            n = int(it.get("n"))
        except (TypeError, ValueError):
            problems.append(f"item without a line number: {it!r}"[:120])
            continue
        e = str(it.get("emotion", "")).strip().lower()
        i = str(it.get("intensity", "")).strip().lower()
        p = str(it.get("pace", "normal")).strip().lower()
        if not 1 <= n <= count:
            problems.append(f"line {n} does not exist")
        elif e not in EMOTIONS or i not in INTENSITIES or p not in PACES:
            problems.append(f"line {n}: '{e}/{i}/{p}' is not in the vocabulary")
        else:
            out[n] = (e, i, p)
    return out, problems


Complete = Callable[[str, str], str]   # (system, user) -> model text


def llama_complete(model_path: str, n_ctx: int = 4096) -> Complete:
    """A completion function backed by llama.cpp (loaded once)."""
    from llama_cpp import Llama  # type: ignore
    llm = Llama(model_path=model_path, n_ctx=n_ctx, verbose=False)

    def complete(system: str, user: str) -> str:
        out = llm.create_chat_completion(
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            response_format={"type": "json_object", "schema": REPLY_SCHEMA},
            max_tokens=60 * (user.count("\n") + 1) + 200, temperature=0.2)
        return out["choices"][0]["message"]["content"]
    return complete


def suggest_directions(project, complete: Complete, batch_size: int = 12,
                       cancel: Optional[Callable[[], bool]] = None) -> SuggestionReport:
    """Ask the model for unapproved lines that have no script direction yet."""
    rep = SuggestionReport()
    todo = []
    for d in project.dialogue:
        dd = project.director.line(d.id)
        if dd is None:
            continue
        if not _editable(dd):
            rep.skipped_locked += 1
        elif dd.source == DirectionSource.SCRIPT and dd.emotion:
            rep.kept_script += 1     # the writer's own direction wins
        else:
            todo.append(d.id)
    for start in range(0, len(todo), batch_size):
        if cancel and cancel():
            break
        ids = todo[start:start + batch_size]
        reply = complete(SYSTEM_PROMPT, build_prompt(project, ids))
        got, problems = parse_reply(reply, len(ids))
        rep.rejected += problems
        for n, (e, i, p) in got.items():
            dd = project.director.line(ids[n - 1])
            if dd.source == DirectionSource.SCRIPT:
                # Partial script direction (e.g. "(quietly)": soft and slow):
                # the model only fills what the writer left open.
                filled = [k for k, v in (("emotion", dd.emotion), ("intensity", dd.intensity),
                                         ("pace", dd.pace)) if v is None]
                dd.emotion = dd.emotion or e
                dd.intensity = dd.intensity or i
                dd.pace = dd.pace or p
                dd.note = f"{dd.note}; {', '.join(filled)} suggested by the local script model"
            else:
                dd.emotion, dd.intensity, dd.pace = e, i, p
                dd.note = "suggested by the local script model"
            dd.source = DirectionSource.SUGGESTED
            dd.approved = False
            rep.suggested += 1
    project.touch()
    return rep


# ---- approval -------------------------------------------------------------------

def set_direction(project, line_id: str, emotion: Optional[str], intensity: Optional[str],
                  pace: Optional[str]) -> LineDirection:
    """The user's own choice for a line: validated, approved immediately."""
    for val, allowed, what in ((emotion, EMOTIONS, "emotion"),
                               (intensity, INTENSITIES, "intensity"),
                               (pace, PACES, "pace")):
        if val is not None and val not in allowed:
            raise ValueError(f"unknown {what}: {val}")
    dd = project.director.line(line_id)
    if dd is None:
        raise KeyError(line_id)
    dd.emotion, dd.intensity, dd.pace = emotion, intensity, pace
    dd.source, dd.note, dd.approved = DirectionSource.USER, "set by you", True
    project.touch()
    return dd


def approve_line(project, line_id: str) -> LineDirection:
    dd = project.director.line(line_id)
    if dd is None:
        raise KeyError(line_id)
    dd.approved = True
    project.touch()
    return dd


def approve_plan(project) -> None:
    """Approve the breakdown. Every line must have an approved direction."""
    pending = [d.line_id for d in project.director.lines if not d.approved]
    if pending:
        raise ValueError(f"{len(pending)} line(s) still need their direction approved.")
    project.director.plan_approved = True
    project.touch()


def unapprove_plan(project) -> None:
    project.director.plan_approved = False
    project.touch()


# ---- read-only access for other modules (e.g. per-line voicing) ------------------

@dataclass(frozen=True)
class ApprovedDirection:
    emotion: Optional[str]
    intensity: Optional[str]
    pace: Optional[str]


def approved_direction(project, line_id: str) -> Optional[ApprovedDirection]:
    """The approved delivery for a dialogue line, or None if not approved.

    Unapproved suggestions are never returned, so nothing downstream can act
    on a direction the user has not accepted.
    """
    dd = project.director.line(line_id)
    if dd is None or not dd.approved:
        return None
    return ApprovedDirection(dd.emotion, dd.intensity, dd.pace)
