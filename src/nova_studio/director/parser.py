"""Deterministic script parser: Fountain screenplays and plain "Name: line" text.

No model is involved, so the same script always gives the same breakdown.
Supported Fountain elements: title page, scene headings (INT./EXT./EST./
INT./EXT./I/E and forced ".HEADING"), action, character cues (with
extensions such as (V.O.) and (CONT'D), forced "@Name", dual-dialogue "^"),
parentheticals, dialogue, transitions ("CUT TO:" and forced ">"), notes
[[...]] and boneyard /* ... */ (both ignored). Plain scripts may write
dialogue as "Name: line", optionally starting with a parenthetical.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

TITLE_KEYS = {
    "title", "credit", "author", "authors", "source", "draft date", "date",
    "contact", "copyright", "notes", "revision",
}

_HEADING = re.compile(
    r"^(?P<ie>INT\.?/EXT|EXT\.?/INT|INT|EXT|EST|I/E)[\.\s]\s*(?P<rest>.*)$",
    re.IGNORECASE)
_CUE = re.compile(r"^(?P<name>[A-Z0-9][A-Z0-9 .'\-]*?)\s*(?:\((?P<ext>[^)]*)\))?\s*(?P<dual>\^)?$")
_PLAIN = re.compile(r"^(?P<name>[A-Za-z][A-Za-z0-9 .'\-]{0,40}?)\s*(?:\((?P<ext>[^)]*)\))?\s*:\s+(?P<text>\S.*)$")
_PAREN = re.compile(r"^\((?P<p>[^)]*)\)$")
_LEAD_PAREN = re.compile(r"^\((?P<p>[^)]*)\)\s*(?P<rest>.*)$")
_TIME_WORDS = {"DAY", "NIGHT", "MORNING", "EVENING", "AFTERNOON", "DAWN", "DUSK",
               "LATER", "CONTINUOUS", "MOMENTS LATER", "SAME", "SUNSET", "SUNRISE"}


class ElementKind(str, Enum):
    ACTION = "action"
    DIALOGUE = "dialogue"
    TRANSITION = "transition"


@dataclass
class ParsedScene:
    index: int
    heading: str
    int_ext: str = ""
    location: str = ""
    time_of_day: str = ""
    implicit: bool = False
    line_no: int = 0


@dataclass
class Element:
    kind: ElementKind
    text: str
    scene_index: int
    line_no: int
    speaker: str = ""          # display name, e.g. "Elaine Vance"
    parenthetical: str = ""
    extension: str = ""
    dual: bool = False


@dataclass
class ParsedScript:
    title: str = ""
    format: str = ""
    scenes: list[ParsedScene] = field(default_factory=list)
    elements: list[Element] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def speakers(self) -> list[str]:
        """Unique speakers in order of first line (case-insensitive)."""
        seen: dict[str, str] = {}
        for e in self.elements:
            if e.kind == ElementKind.DIALOGUE and e.speaker.lower() not in seen:
                seen[e.speaker.lower()] = e.speaker
        return list(seen.values())

    @property
    def dialogue(self) -> list[Element]:
        return [e for e in self.elements if e.kind == ElementKind.DIALOGUE]


def _strip_markup(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"\[\[.*?\]\]", "", text, flags=re.S)


def _norm(text: str) -> str:
    """Collapse runs of whitespace (e.g. left behind by a removed note)."""
    return " ".join(text.split())


def display_name(raw: str) -> str:
    """'ELAINE VANCE' -> 'Elaine Vance'; mixed-case names are kept as written."""
    name = " ".join(raw.split()).strip(" .")
    if name.isupper():
        name = " ".join(w.capitalize() if not re.fullmatch(r"[IVX]+", w) else w
                        for w in name.split(" "))
    return name


def _clean_extension(ext: Optional[str]) -> str:
    if not ext:
        return ""
    parts = [p.strip() for p in ext.replace(";", ",").split(",")]
    keep = [p for p in parts if p and p.upper().replace("'", "").replace("’", "") not in {"CONTD", "CONT", "CONTINUED"}]
    return ", ".join(keep)


def _parse_heading(line: str) -> Optional[tuple[str, str, str, str]]:
    """Return (heading, int_ext, location, time) or None."""
    s = line.strip()
    if s.startswith(".") and not s.startswith(".."):
        heading = s[1:].strip()
        return heading, "", heading, ""
    m = _HEADING.match(s)
    if not m:
        return None
    ie = m.group("ie").upper().replace(".", "")
    ie = {"I/E": "INT/EXT", "EXT/INT": "INT/EXT"}.get(ie, ie)
    rest = re.sub(r"\s*#[^#]*#\s*$", "", m.group("rest")).strip()  # scene numbers
    location, time = rest, ""
    if " - " in rest:
        location, time = rest.rsplit(" - ", 1)
        if time.strip().upper() not in _TIME_WORDS and not time.strip().isupper():
            location, time = rest, ""
    return s, ie, location.strip(), time.strip()


def _is_cue(line: str) -> Optional[tuple[str, str, bool]]:
    s = line.strip()
    if s.startswith("@"):  # forced cue: any capitalisation
        raw = s[1:].strip()
        dual = raw.endswith("^")
        name, _, ext = raw.rstrip("^ ").partition("(")
        return display_name(name), _clean_extension(ext.rstrip(") ")), dual
    if not any(c.isalpha() for c in s) or s != s.upper() or s.endswith(":"):
        return None
    m = _CUE.match(s)
    # A capitalised sentence ("THE DOOR SLAMS.") is action, not a speaker.
    if not m or m.group("name").endswith("."):
        return None
    return display_name(m.group("name")), _clean_extension(m.group("ext")), bool(m.group("dual"))


def _is_transition(line: str) -> Optional[str]:
    s = line.strip()
    if s.startswith(">") and not s.endswith("<"):
        return s[1:].strip()
    if s.isupper() and s.endswith("TO:"):
        return s
    return None


def _title_page(lines: list[str]) -> tuple[str, int]:
    """Consume a Fountain title page. Returns (title, first body line index)."""
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    m = re.match(r"^([A-Za-z ]+):\s*(.*)$", lines[i]) if i < len(lines) else None
    if not m or m.group(1).strip().lower() not in TITLE_KEYS:
        return "", 0
    title = ""
    key = ""
    while i < len(lines) and lines[i].strip():
        m = re.match(r"^([A-Za-z ]+):\s*(.*)$", lines[i])
        if m and m.group(1).strip().lower() in TITLE_KEYS:
            key = m.group(1).strip().lower()
            if key == "title" and m.group(2).strip():
                title = m.group(2).strip()
        elif key == "title" and not title:
            title = lines[i].strip()
        i += 1
    return re.sub(r"[_*]", "", title).strip(), i


def parse_script(text: str) -> ParsedScript:
    out = ParsedScript()
    lines = _strip_markup(text.replace("\r\n", "\n").replace("\r", "\n")).split("\n")
    out.title, i = _title_page(lines)

    scene_index = -1
    used_fountain = used_plain = False

    def ensure_scene(line_no: int) -> int:
        nonlocal scene_index
        if scene_index < 0:
            scene_index = 0
            out.scenes.append(ParsedScene(0, "", implicit=True, line_no=line_no))
        return scene_index

    action_buf: list[str] = []
    action_start = 0

    def flush_action() -> None:
        nonlocal action_buf
        body = _norm(" ".join(action_buf))
        if body:
            out.elements.append(Element(ElementKind.ACTION, body,
                                        ensure_scene(action_start), action_start))
        action_buf = []

    n = len(lines)
    while i < n:
        raw = lines[i]
        s = raw.strip()
        line_no = i + 1
        prev_blank = i == 0 or not lines[i - 1].strip()
        next_text = i + 1 < n and bool(lines[i + 1].strip())

        if not s:
            flush_action()
            i += 1
            continue

        heading = _parse_heading(s) if prev_blank or not action_buf else None
        if heading:
            flush_action()
            scene_index += 1
            h, ie, loc, tod = heading
            out.scenes.append(ParsedScene(scene_index, h, ie, loc, tod, line_no=line_no))
            used_fountain = True
            i += 1
            continue

        trans = _is_transition(s) if prev_blank else None
        if trans:
            flush_action()
            out.elements.append(Element(ElementKind.TRANSITION, trans,
                                        ensure_scene(line_no), line_no))
            used_fountain = True
            i += 1
            continue

        cue = _is_cue(s) if (prev_blank and next_text) else None
        if cue:
            flush_action()
            name, ext, dual = cue
            used_fountain = True
            i += 1
            paren, chunk, chunk_line = "", [], i + 1
            while i < n and lines[i].strip():
                t = lines[i].strip()
                pm = _PAREN.match(t)
                if pm:
                    if chunk:
                        out.elements.append(Element(
                            ElementKind.DIALOGUE, _norm(" ".join(chunk)), ensure_scene(chunk_line),
                            chunk_line, name, paren, ext, dual))
                        chunk = []
                    paren, chunk_line = f"({pm.group('p').strip()})", i + 1
                else:
                    if not chunk:
                        chunk_line = i + 1
                    chunk.append(t)
                i += 1
            if chunk:
                out.elements.append(Element(
                    ElementKind.DIALOGUE, _norm(" ".join(chunk)), ensure_scene(chunk_line),
                    chunk_line, name, paren, ext, dual))
            elif paren:
                out.warnings.append(f"Line {line_no}: {name} has a parenthetical but no dialogue.")
            continue

        pm = _PLAIN.match(s)
        if pm and pm.group("name").strip().lower() not in TITLE_KEYS:
            flush_action()
            used_plain = True
            body = pm.group("text").strip()
            paren = ""
            lp = _LEAD_PAREN.match(body)
            if lp and lp.group("rest"):
                paren, body = f"({lp.group('p').strip()})", lp.group("rest").strip()
            out.elements.append(Element(
                ElementKind.DIALOGUE, _norm(body), ensure_scene(line_no), line_no,
                display_name(pm.group("name")), paren, _clean_extension(pm.group("ext"))))
            i += 1
            continue

        if not action_buf:
            action_start = line_no
        action_buf.append(raw)
        i += 1
    flush_action()

    out.format = ("mixed" if used_fountain and used_plain else
                  "plain" if used_plain else "fountain" if used_fountain else "plain")
    if not out.elements and not out.scenes:
        out.warnings.append("The script is empty.")
    elif all(sc.implicit for sc in out.scenes):
        out.warnings.append("No scene headings found (e.g. 'INT. KITCHEN - NIGHT'); "
                            "everything was placed in one scene.")
    if out.elements and not out.dialogue:
        out.warnings.append("No dialogue found. Character cues are names in CAPITALS "
                            "on their own line, or 'Name: line'.")
    return out
