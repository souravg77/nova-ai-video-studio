"""Render a character reference sheet (PNG) from the character's data.

Layout: identity header; the approved design as the hero image; the
turnaround row; the expression row; a palette measured from the approved
image; and an approval stamp. Empty slots are drawn as labelled empty boxes.
An unapproved character gets a "DRAFT - NOT APPROVED" sheet with no hero
image, so a draft can never be mistaken for an approved identity.

Rendering is deterministic: the same character data gives the same pixels.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont, ImageOps

from ..performance.characters import Character
from .views import EXPRESSIONS, TURNAROUND, expression_slot, slot_label, view_path

W, H = 1800, 1150
MARGIN = 40
BG = (247, 244, 238)
INK = (34, 34, 34)
MUTED = (130, 126, 118)
EMPTY = (226, 222, 214)
APPROVED_GREEN = (46, 125, 50)
DRAFT_RED = (198, 40, 40)


@dataclass
class SheetReport:
    path: str
    approved: bool
    version: Optional[int]
    filled: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    palette: list[str] = field(default_factory=list)   # hex colours
    warnings: list[str] = field(default_factory=list)


def _font(size: int, bold: bool = False):
    names = (["arialbd.ttf", "DejaVuSans-Bold.ttf"] if bold
             else ["arial.ttf", "DejaVuSans.ttf"])
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _open(path: Optional[str]) -> Optional[Image.Image]:
    if not path or not Path(path).is_file():
        return None
    try:
        with Image.open(path) as im:
            return ImageOps.exif_transpose(im).convert("RGB")
    except OSError:
        return None


def _place(sheet: Image.Image, img: Optional[Image.Image], box, label: str,
           draw: ImageDraw.ImageDraw, small) -> bool:
    x0, y0, x1, y1 = box
    label_h = 26
    area = (x0, y0, x1, y1 - label_h)
    if img is None:
        draw.rectangle(area, fill=EMPTY)
        # dashed outline
        for x in range(x0, x1, 14):
            draw.line([(x, y0), (min(x + 7, x1), y0)], fill=MUTED)
            draw.line([(x, area[3]), (min(x + 7, x1), area[3])], fill=MUTED)
        for y in range(y0, area[3], 14):
            draw.line([(x0, y), (x0, min(y + 7, area[3]))], fill=MUTED)
            draw.line([(x1, y), (x1, min(y + 7, area[3]))], fill=MUTED)
        draw.text(((x0 + x1) / 2, (y0 + area[3]) / 2), "empty", fill=MUTED,
                  font=small, anchor="mm")
        filled = False
    else:
        fitted = ImageOps.contain(img, (x1 - x0, area[3] - y0), Image.LANCZOS)
        ox = x0 + (x1 - x0 - fitted.width) // 2
        oy = y0 + (area[3] - y0 - fitted.height) // 2
        sheet.paste(fitted, (ox, oy))
        filled = True
    draw.text(((x0 + x1) / 2, y1 - label_h / 2), label, fill=INK, font=small, anchor="mm")
    return filled


def palette(img: Image.Image, n: int = 6) -> list[tuple[int, int, int]]:
    """Dominant colours, most common first (deterministic median cut)."""
    small = img.copy()
    small.thumbnail((200, 200))
    q = small.quantize(colors=n, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()[: n * 3]
    counts = sorted(q.getcolors(), reverse=True)
    return [tuple(pal[i * 3: i * 3 + 3]) for _, i in counts][:n]


def render_sheet(c: Character, out_path: str | Path, project_title: str = "") -> SheetReport:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    approved = c.approved is not None
    rep = SheetReport(path=str(out), approved=approved,
                      version=c.approved.version if approved else None)

    sheet = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(sheet)
    big, mid, small, tiny = _font(54, True), _font(26, True), _font(20), _font(17)

    # ---- header ----------------------------------------------------------------
    d.text((MARGIN, MARGIN), c.name, fill=INK, font=big)
    sub = " · ".join(x for x in (project_title, c.description) if x)
    if sub:
        d.text((MARGIN, MARGIN + 70), sub[:150], fill=MUTED, font=small)
    facts = []
    if c.height_cm:
        facts.append(f"Height {c.height_cm:g} cm")
    v = c.voice
    facts.append(f"Voice: {v.voice_id or 'not assigned'}" + (f" ({v.engine_id})" if v.engine_id else ""))
    facts.append(f"Language: {v.language}" + (f", {v.accent}" if v.accent else ""))
    d.text((MARGIN, MARGIN + 100), "   ".join(facts), fill=INK, font=tiny)

    top = MARGIN + 150
    # ---- hero (approved design only) ---------------------------------------------
    hero_box = (MARGIN, top, MARGIN + 520, top + 760)
    hero = _open(c.approved.image_path) if approved else None
    hero_label = (f"Approved design v{c.approved.version}" if approved else "No approved design")
    _place(sheet, hero, hero_box, hero_label, d, small)

    # ---- turnaround ------------------------------------------------------------------
    x = MARGIN + 560
    d.text((x, top - 8), "TURNAROUND", fill=MUTED, font=mid, anchor="ls")
    tw, th, gap = 220, 360, 14
    for i, slot in enumerate(TURNAROUND):
        bx = x + i * (tw + gap)
        img = _open(view_path(c, slot))
        ok = _place(sheet, img, (bx, top + 10, bx + tw, top + 10 + th), slot_label(slot), d, small)
        (rep.filled if ok else rep.missing).append(slot)

    # ---- expressions -------------------------------------------------------------------
    ey = top + th + 70
    d.text((x, ey - 8), "EXPRESSIONS", fill=MUTED, font=mid, anchor="ls")
    ew, eh, egap = 150, 190, 11
    for i, emo in enumerate(EXPRESSIONS):
        slot = expression_slot(emo)
        bx = x + i * (ew + egap)
        img = _open(view_path(c, slot))
        ok = _place(sheet, img, (bx, ey + 10, bx + ew, ey + 10 + eh), slot_label(slot), d, tiny)
        (rep.filled if ok else rep.missing).append(slot)

    # ---- palette ------------------------------------------------------------------------
    py = ey + eh + 70
    d.text((x, py - 8), "PALETTE (measured from the approved design)", fill=MUTED, font=mid, anchor="ls")
    if hero is not None:
        for i, rgb in enumerate(palette(hero)):
            bx = x + i * 160
            d.rectangle((bx, py + 10, bx + 140, py + 70), fill=rgb)
            hexv = "#%02x%02x%02x" % rgb
            rep.palette.append(hexv)
            d.text((bx + 70, py + 88), hexv, fill=INK, font=tiny, anchor="mm")
    else:
        d.text((x, py + 30), "No approved design to measure.", fill=MUTED, font=small)

    # ---- stamp ----------------------------------------------------------------------------
    sy = H - MARGIN - 60
    if approved:
        state = "LOCKED" if c.locked else "not locked"
        when = c.approved.approved_at[:10]
        stamp = f"APPROVED v{c.approved.version} · {when} · {state}"
        d.rectangle((W - MARGIN - 640, sy, W - MARGIN, sy + 60), outline=APPROVED_GREEN, width=4)
        d.text((W - MARGIN - 320, sy + 30), stamp, fill=APPROVED_GREEN, font=mid, anchor="mm")
        if not c.locked:
            rep.warnings.append(f"{c.name} is approved but not locked.")
        if c.approved.is_placeholder:
            rep.warnings.append("The approved design is a placeholder image.")
    else:
        d.rectangle((W - MARGIN - 640, sy, W - MARGIN, sy + 60), outline=DRAFT_RED, width=4)
        d.text((W - MARGIN - 320, sy + 30), "DRAFT - NOT APPROVED", fill=DRAFT_RED, font=mid, anchor="mm")
        rep.warnings.append(f"{c.name} has no approved design; this is a draft sheet.")
    d.text((MARGIN, H - MARGIN - 30),
           "Empty slots have no approved reference yet. Nothing on this sheet is generated by the sheet itself.",
           fill=MUTED, font=tiny)

    # Deterministic PNG: no timestamps or text chunks.
    sheet.save(out, format="PNG", optimize=False)
    return rep
