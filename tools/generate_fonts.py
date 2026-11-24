"""Rasterise open DejaVu fonts (Bitstream Vera licence) + UI icons into crisp 1-bit C tables.

FreeType is driven in non-antialiased mode ("1"), so every glyph is hinted
pixel-exact at its target size: zero gray, zero dithering.

Output: firmware/components/ui_core/fonts_gen.c, icons_gen.c
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
TTF = Path(matplotlib.get_data_path()) / "fonts/ttf"
OUT = ROOT / "firmware/components/ui_core"

# extra code points remapped into 127.. so C can index a dense table
EXTRA = {0x00B7: 127, 0x2014: 128, 0x2026: 129}
FONTS = [  # (C name, ttf, px size, first, last)
    ("FONT_14", "DejaVuSans.ttf", 14, 32, 129),
    ("FONT_16", "DejaVuSans.ttf", 16, 32, 129),
    ("FONT_16B", "DejaVuSans-Bold.ttf", 16, 32, 129),
    ("FONT_24B", "DejaVuSans-Bold.ttf", 24, 32, 129),
    ("FONT_32B", "DejaVuSans-Bold.ttf", 32, 32, 129),
    ("FONT_64", "DejaVuSansMono-Bold.ttf", 64, 32, 58),
]


def char_for(code: int) -> str:
    for cp, idx in EXTRA.items():
        if idx == code:
            return chr(cp)
    return chr(code) if code < 127 else ""


def pack_rows(img: Image.Image) -> bytes:
    w, h = img.size
    px = img.load()
    out = bytearray()
    for y in range(h):
        for bx in range(0, w, 8):
            b = 0
            for i in range(8):
                if bx + i < w and px[bx + i, y]:
                    b |= 0x80 >> i
            out.append(b)
    return bytes(out)


def gen_font(name: str, ttf: str, size: int, first: int, last: int) -> list[str]:
    font = ImageFont.truetype(str(TTF / ttf), size)
    ascent, descent = font.getmetrics()
    glyphs, bitmap = [], bytearray()
    for code in range(first, last + 1):
        ch = char_for(code)
        if not ch or (name == "FONT_64" and ch not in "0123456789: "):
            glyphs.append((len(bitmap), 0, 0, 0, 0, 0))
            continue
        adv = int(round(font.getlength(ch)))
        x0, y0, x1, y1 = font.getbbox(ch, anchor="la")
        w, h = max(x1 - x0, 0), max(y1 - y0, 0)
        if w and h:
            img = Image.new("1", (w, h), 0)
            dr = ImageDraw.Draw(img)
            dr.fontmode = "1"  # FreeType mono rendering: hinted, zero antialiasing
            dr.text((-x0, -y0), ch, font=font, fill=1, anchor="la")
            data = pack_rows(img)
        else:
            data = b""
        glyphs.append((len(bitmap), w, h, x0, y0, adv))
        bitmap += data
    lines = [f"static const uint8_t {name}_bits[] = {{"]
    for off in range(0, len(bitmap), 24):
        lines.append("  " + ",".join(f"0x{b:02X}" for b in bitmap[off:off + 24]) + ",")
    if not bitmap:
        lines.append("  0")
    lines.append("};")
    lines.append(f"static const font_glyph_t {name}_glyphs[] = {{")
    for g in glyphs:
        lines.append("  {%d,%d,%d,%d,%d,%d}," % g)
    lines.append("};")
    lines.append(f"const font_t {name} = {{{first}, {last - first + 1}, {ascent + descent}, "
                 f"{ascent}, {name}_glyphs, {name}_bits}};")
    return lines


# --- icons: 4x supersampled, white-on-transparent masks (bit 1 = draw) -----------
ICON = 18


def icon(draw_fn) -> Image.Image:
    s = 4
    img = Image.new("L", (ICON * s, ICON * s), 0)
    draw_fn(ImageDraw.Draw(img), s)
    return img.resize((ICON, ICON), Image.BOX).point(lambda v: 255 if v >= 128 else 0).convert("1")


def ring(d, s):
    d.ellipse([1 * s, 1 * s, 17 * s, 17 * s], outline=255, width=2 * s)


def i_arrow(d, s):
    ring(d, s)
    d.line([5 * s, 9 * s, 12 * s, 9 * s], fill=255, width=2 * s)
    d.polygon([(10 * s, 5 * s), (14 * s, 9 * s), (10 * s, 13 * s)], fill=255)


def i_check(d, s):
    ring(d, s)
    d.line([(5 * s, 9 * s), (8 * s, 12 * s), (13 * s, 6 * s)], fill=255, width=2 * s, joint="curve")


def i_pause(d, s):
    ring(d, s)
    d.rectangle([6 * s, 5.5 * s, 8 * s, 12.5 * s], fill=255)
    d.rectangle([10 * s, 5.5 * s, 12 * s, 12.5 * s], fill=255)


def i_play(d, s):
    ring(d, s)
    d.polygon([(7 * s, 5 * s), (13 * s, 9 * s), (7 * s, 13 * s)], fill=255)


def i_cycle(d, s):
    d.arc([2 * s, 2 * s, 16 * s, 16 * s], 40, 330, fill=255, width=2 * s)
    d.polygon([(11 * s, 1 * s), (17 * s, 3 * s), (13 * s, 8 * s)], fill=255)


def i_link(d, s):
    d.rounded_rectangle([1 * s, 6 * s, 10 * s, 12 * s], radius=3 * s, outline=255, width=2 * s)
    d.rounded_rectangle([8 * s, 6 * s, 17 * s, 12 * s], radius=3 * s, outline=255, width=2 * s)


def i_link_off(d, s):
    i_link(d, s)
    d.line([(2 * s, 16 * s), (16 * s, 2 * s)], fill=0, width=4 * s)
    d.line([(2 * s, 16 * s), (16 * s, 2 * s)], fill=255, width=2 * s)


def i_bell(d, s):
    d.pieslice([3 * s, 2 * s, 15 * s, 16 * s], 180, 360, fill=255)
    d.rectangle([3 * s, 9 * s, 15 * s, 13 * s], fill=255)
    d.rectangle([1 * s, 13 * s, 17 * s, 14.5 * s], fill=255)
    d.ellipse([7 * s, 14 * s, 11 * s, 18 * s], fill=255)


def i_mic(d, s):
    d.rounded_rectangle([6 * s, 1 * s, 12 * s, 11 * s], radius=3 * s, fill=255)
    d.arc([3 * s, 4 * s, 15 * s, 14 * s], 0, 180, fill=255, width=2 * s)
    d.line([9 * s, 14 * s, 9 * s, 17 * s], fill=255, width=2 * s)


ICONS = [("ARROW", i_arrow), ("CHECK", i_check), ("PAUSE", i_pause), ("PLAY", i_play),
         ("CYCLE", i_cycle), ("LINK", i_link), ("LINK_OFF", i_link_off), ("BELL", i_bell),
         ("MIC", i_mic)]


def gen_icons() -> str:
    lines = ["/* GENERATED by tools/generate_fonts.py - do not edit. */", '#include "icons.h"',
             f"const uint8_t ui_icons[UI_ICON_COUNT][{ICON * 3}] = {{"]
    for name, fn in ICONS:
        data = pack_rows(icon(fn))
        lines.append(f"  /* {name} */ {{" + ",".join(f"0x{b:02X}" for b in data) + "},")
    lines.append("};")
    return "\n".join(lines) + "\n"


def main() -> int:
    out = ["/* GENERATED by tools/generate_fonts.py from DejaVu fonts - do not edit. */",
           '#include "font.h"']
    for spec in FONTS:
        out += gen_font(*spec)
    (OUT / "fonts_gen.c").write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
    (OUT / "icons_gen.c").write_text(gen_icons(), encoding="utf-8", newline="\n")
    print("fonts + icons generated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
