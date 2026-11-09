"""Qt-free logic behind the workspace shell (roadmap M1 step 2).

Kept separate from the widgets so it can be unit-tested without PySide6: which
creative modes exist and whether they are built, what the Library lists, what
the Inspector shows for a selection, and how jobs appear in the queue panel.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class Mode:
    key: str
    title: str
    built: bool
    # For unbuilt modes: when it is planned and what to use meanwhile.
    planned: str = ""
    summary: str = ""
    meanwhile: str = ""


MODES: tuple[Mode, ...] = (
    Mode("script", "Script", False, "M2 - AI Director",
         "Write or import a script; NOVA extracts scenes, speakers, dialogue, "
         "actions and locations for you to approve.",
         "To draft a narrated video from a short brief today, use "
         "'Auto video from brief' in Edit & render."),
    Mode("characters", "Characters", False, "M3 - Character Studio",
         "Create, compare and approve character designs and reference sheets, "
         "then lock each approved identity and assign its voice.",
         "To make a narrated video from photos today, use "
         "'Make photo video' in Edit & render."),
    Mode("storyboard", "Storyboard", False, "M2 - Storyboard & shot planner",
         "Turn the approved script into scenes and shots with camera, "
         "framing, duration and start/end frames, and approve the plan.",
         "Scenes can be ordered and timed in Edit & render."),
    Mode("generate", "Generate", False, "M5 - Generation engines",
         "Generate shots with an installed or opted-in engine, compare takes "
         "and keep approved versions.",
         "No AI video engine is available in this build. Edit & render "
         "produces videos from your own photos and footage."),
    Mode("edit", "Edit & render", True,
         summary="Import media, arrange scenes, narrate, subtitle and export "
                 "a validated MP4."),
)

DEFAULT_MODE = "edit"


def mode(key: str) -> Mode:
    for m in MODES:
        if m.key == key:
            return m
    raise KeyError(key)


def placeholder_text(m: Mode) -> str:
    return (f"{m.title} is not built yet (planned: {m.planned}).\n\n"
            f"{m.summary}\n\n{m.meanwhile}")


# ---- Library ---------------------------------------------------------------

@dataclass(frozen=True)
class LibraryEntry:
    group: str          # "Assets", "Scenes", "Characters", ...
    item_id: str
    label: str


def library_entries(project) -> list[LibraryEntry]:
    """Everything in the open project, grouped. Tolerates older projects."""
    out: list[LibraryEntry] = []
    for a in getattr(project, "assets", []) or []:
        name = str(getattr(a, "path", "")).replace("\\", "/").rsplit("/", 1)[-1]
        kind = getattr(getattr(a, "kind", None), "value", getattr(a, "kind", ""))
        mark = "" if getattr(a, "valid", False) else "  (not validated)"
        out.append(LibraryEntry("Assets", a.id, f"[{kind}] {name}{mark}"))
    for s in sorted(getattr(project, "scenes", []) or [],
                    key=lambda s: getattr(s, "index", 0)):
        title = getattr(s, "title", "") or "Untitled scene"
        out.append(LibraryEntry(
            "Scenes", s.id,
            f"{getattr(s, 'index', 0) + 1}. {title} ({getattr(s, 'duration_s', 0):g}s)"))
    # Schema v2 projects carry characters; older ones simply have none.
    for c in getattr(project, "characters", []) or []:
        name = getattr(c, "name", "") or "Unnamed character"
        out.append(LibraryEntry("Characters", getattr(c, "id", name), name))
    return out


def _fmt(v: Any) -> str:
    if v is None or v == "":
        return "-"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:g}"
    return str(getattr(v, "value", v))


def inspector_rows(project, group: str, item_id: str) -> list[tuple[str, str]]:
    """Read-only properties of the selected Library item."""
    if group == "Assets":
        a = next((a for a in project.assets if a.id == item_id), None)
        if a is None:
            return []
        res = (f"{a.width}x{a.height}" if a.width and a.height else None)
        return [("Kind", _fmt(a.kind)), ("File", _fmt(a.path)),
                ("Duration (s)", _fmt(a.duration_s)), ("Resolution", _fmt(res)),
                ("Codec", _fmt(a.codec)), ("Validated", _fmt(a.valid)),
                ("Note", _fmt(a.note))]
    if group == "Scenes":
        s = next((s for s in project.scenes if s.id == item_id), None)
        if s is None:
            return []
        visual = project.asset_by_id(s.visual_asset_id) if s.visual_asset_id else None
        narr = project.asset_by_id(s.narration_asset_id) if s.narration_asset_id else None
        return [("Order", str(s.index + 1)), ("Title", _fmt(s.title)),
                ("Duration (s)", _fmt(s.duration_s)),
                ("Visual", _fmt(visual.path if visual else None)),
                ("Narration", _fmt(narr.path if narr else None)),
                ("Caption", _fmt(s.caption)), ("Motion", _fmt(s.motion_effect)),
                ("Script", _fmt(s.script))]
    if group == "Characters":
        c = next((c for c in getattr(project, "characters", []) or []
                  if getattr(c, "id", None) == item_id), None)
        if c is None:
            return []
        fields = getattr(c, "model_dump", lambda: {})()
        return [(k.replace("_", " ").capitalize(), _fmt(v))
                for k, v in fields.items() if not isinstance(v, (list, dict))]
    return []


# ---- Jobs ------------------------------------------------------------------

def job_row(job) -> tuple[str, str, str, str]:
    """(kind, state, progress, latest message) for the queue panel."""
    kind = _fmt(job.kind).replace("_", " ")
    state = _fmt(job.state).replace("_", " ")
    progress = f"{int(round((job.progress or 0) * 100))}%"
    detail = job.blocker or (job.logs[-1].message if job.logs else "")
    return kind, state, progress, detail


def engines_summary(settings, gemini_available: bool) -> str:
    """Honest one-liner for the toolbar: what may run, and where."""
    parts = ["Local engines (offline)"]
    if settings.cloud.gemini_enabled and gemini_available:
        parts.append(f"cloud opt-in: {settings.cloud.gemini_model}")
    return " + ".join(parts)


def title_for(project_name: Optional[str]) -> str:
    return f"{project_name or 'Untitled Project'} - NOVA AI Video Studio"


def library_signature(project) -> tuple:
    """Cheap fingerprint used to refresh the Library only when content changes."""
    return (getattr(project, "name", ""),
            tuple((a.id, a.valid) for a in getattr(project, "assets", []) or []),
            tuple((s.id, s.index, s.title, s.duration_s)
                  for s in getattr(project, "scenes", []) or []),
            tuple(getattr(c, "id", "") for c in getattr(project, "characters", []) or []))
