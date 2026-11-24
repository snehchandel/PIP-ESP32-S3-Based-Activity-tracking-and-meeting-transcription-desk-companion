"""PIP mascot vector geometry (drawn at 4x supersampling, thresholded to 1-bit later).

All coordinates below are in final 120x120 sprite pixels; the helpers scale by SS.
Anatomy (invariant across expressions): sensor mast + ball tip, side fins,
spherical body, black display visor with white eyes, status badge, stabilizer pads.
"""
from __future__ import annotations

import math

from PIL import Image, ImageDraw

SIZE = 120
SS = 4
INK = 0      # black in "L" mode
PAPER = 255  # white
STROKE = 3   # bold outer contour, final px


def _s(v: float) -> int:
    return int(round(v * SS))


class Canvas:
    def __init__(self) -> None:
        self.img = Image.new("L", (SIZE * SS, SIZE * SS), PAPER)
        self.d = ImageDraw.Draw(self.img)

    # -- outlined primitives -------------------------------------------------
    def ellipse(self, x0, y0, x1, y1, fill=PAPER, stroke=STROKE):
        self.d.ellipse([_s(x0), _s(y0), _s(x1), _s(y1)], fill=INK)
        if fill == PAPER and stroke:
            self.d.ellipse([_s(x0 + stroke), _s(y0 + stroke), _s(x1 - stroke), _s(y1 - stroke)], fill=PAPER)

    def rrect(self, x0, y0, x1, y1, r, fill=PAPER, stroke=STROKE):
        self.d.rounded_rectangle([_s(x0), _s(y0), _s(x1), _s(y1)], radius=_s(r), fill=INK)
        if fill == PAPER and stroke:
            self.d.rounded_rectangle(
                [_s(x0 + stroke), _s(y0 + stroke), _s(x1 - stroke), _s(y1 - stroke)],
                radius=_s(max(r - stroke, 1)), fill=PAPER)

    def line(self, pts, width, color=INK):
        self.d.line([(_s(x), _s(y)) for x, y in pts], fill=color, width=_s(width), joint="curve")
        for x, y in (pts[0], pts[-1]):  # round caps
            r = width / 2
            self.d.ellipse([_s(x - r), _s(y - r), _s(x + r), _s(y + r)], fill=color)

    def arc(self, cx, cy, r, start, end, width, color=INK):
        self.d.arc([_s(cx - r), _s(cy - r), _s(cx + r), _s(cy + r)], start, end, fill=color, width=_s(width))

    def poly(self, pts, color=INK):
        self.d.polygon([(_s(x), _s(y)) for x, y in pts], fill=color)

    def dot(self, cx, cy, r, color=INK):
        self.d.ellipse([_s(cx - r), _s(cy - r), _s(cx + r), _s(cy + r)], fill=color)


# --- body parts --------------------------------------------------------------
BODY = (20, 34, 100, 104)          # ~80 x 70 sphere
VISOR = (31, 49, 89, 81)           # ~58 x 32 black face panel
EYE_L, EYE_R = (48, 65), (72, 65)  # eye centres


def mast(c: Canvas, dy: float = 0):
    base = (44, 38 + dy)
    ang = math.radians(24)
    tip = (base[0] - 21 * math.sin(ang), base[1] - 21 * math.cos(ang))
    c.line([base, tip], 3)
    c.ellipse(tip[0] - 5, tip[1] - 5, tip[0] + 5, tip[1] + 5)


def fins(c: Canvas, dy: float = 0, raised: bool = False):
    if raised:  # stubby arms raised celebrating (outlined capsules)
        for a, b in (((24, 64 + dy), (9, 38 + dy)), ((96, 64 + dy), (111, 38 + dy))):
            c.line([a, b], 13)
            c.line([a, b], 7, PAPER)
        return
    c.rrect(12, 56 + dy, 27, 86 + dy, 7)
    c.rrect(93, 56 + dy, 108, 86 + dy, 7)


def pads(c: Canvas, dy: float = 0, tucked: bool = False, lift_right: bool = False):
    h = 9 if tucked else 14
    c.ellipse(32, 104 + dy - h, 54, 106 + dy)
    if not lift_right:
        c.ellipse(66, 104 + dy - h, 88, 106 + dy)


def body(c: Canvas, dy: float = 0, squash: float = 0):
    x0, y0, x1, y1 = BODY
    c.ellipse(x0 - squash, y0 + dy + squash, x1 + squash, y1 + dy)
    # spherical seam lines (panel detail)
    c.arc(60, 72 + dy, 31, 238, 302, 2)
    # status badge: small chin notch
    c.d.rounded_rectangle([_s(55), _s(89 + dy), _s(65), _s(92 + dy)], radius=_s(1.5), fill=INK)


def visor(c: Canvas, dy: float = 0):
    x0, y0, x1, y1 = VISOR
    c.d.rounded_rectangle([_s(x0), _s(y0 + dy), _s(x1), _s(y1 + dy)], radius=_s(10), fill=INK)


# --- eyes (white on black visor) ----------------------------------------------
def eyes_pill(c: Canvas, dx=0.0, dy=0.0, h=14):
    for ex, ey in (EYE_L, EYE_R):
        x, y = ex + dx, ey + dy
        c.d.rounded_rectangle([_s(x - 4), _s(y - h / 2), _s(x + 4), _s(y + h / 2)], radius=_s(4), fill=PAPER)


def eyes_happy(c: Canvas, dy=0.0):  # ^ ^
    for ex, ey in (EYE_L, EYE_R):
        c.arc(ex, ey + 5 + dy, 8, 200, 340, 5, PAPER)


def eyes_closed(c: Canvas, dy=0.0):  # u u
    for ex, ey in (EYE_L, EYE_R):
        c.arc(ex, ey - 5 + dy, 8, 25, 155, 5, PAPER)


def eyes_angled(c: Canvas, dy=0.0, intense=False):  # \ /
    h = 12 if intense else 10
    for sign, (ex, ey) in ((1, EYE_L), (-1, EYE_R)):
        top_in, top_out = ey - h / 2 + 4, ey - h / 2 - 1
        xi, xo = ex + 5 * sign, ex - 5 * sign
        c.poly([(xo, top_out + dy), (xi, top_in + dy), (xi, ey + h / 2 + dy),
                (xo, ey + h / 2 + dy)], PAPER)


def eyes_blink(c: Canvas, dy=0.0):
    for ex, ey in (EYE_L, EYE_R):
        c.d.rounded_rectangle([_s(ex - 5), _s(ey - 1 + dy), _s(ex + 5), _s(ey + 2 + dy)], radius=_s(1), fill=PAPER)


# --- props ------------------------------------------------------------------
def rays(c: Canvas, cx=100, cy=26, n=3, length=9, spread=(-60, 30)):
    a0, a1 = spread
    for i in range(n):
        a = math.radians(a0 + (a1 - a0) * i / max(n - 1, 1))
        r0 = 10
        c.line([(cx + r0 * math.cos(a), cy + r0 * math.sin(a)),
                (cx + (r0 + length) * math.cos(a), cy + (r0 + length) * math.sin(a))], 3)


def sound_waves(c: Canvas):
    for r in (8, 15, 22):
        c.arc(92, 30, r, 285, 355, 3)


def question(c: Canvas):
    c.arc(104, 15, 7, 180, 420, 4)
    c.line([(104, 22), (104, 27)], 4)
    c.dot(104, 34, 2.6)


def shake(c: Canvas):
    """Alarm vibration arcs on both sides of the body: reads as 'ringing' at a glance."""
    for r in (13, 19):
        c.arc(19, 72, r, 145, 215, 2.5)
        c.arc(101, 72, r, -35, 35, 2.5)


def exclaim(c: Canvas):
    c.poly([(101, 2), (109, 2), (107, 25), (103, 25)])
    c.dot(105, 32, 3)
    rays(c, cx=105, cy=17, n=3, length=6, spread=(-20, 40))


def laptop(c: Canvas):
    c.poly([(80, 80), (106, 72), (112, 100), (86, 108)])            # lid outline
    c.poly([(83.5, 83), (103.5, 76.5), (108.5, 97.5), (88, 104)], PAPER)
    c.dot(96, 90, 2.5)                                              # lid logo
    c.poly([(66, 107), (86, 108), (112, 100), (116, 103), (88, 114), (64, 112)])  # base
    c.ellipse(64, 96, 80, 110)                                      # typing pad


def mug(c: Canvas, note=False):
    c.rrect(82, 88, 102, 112, 3)
    c.arc(104, 100, 6, 270, 90, 3)
    c.d.rectangle([_s(85), _s(93), _s(99), _s(95)], fill=INK)
    c.ellipse(70, 94, 88, 110)                                      # pad holding mug
    if note:
        c.dot(103, 22, 4)
        c.line([(106.5, 22), (106.5, 5)], 2.5)
        c.line([(106.5, 5), (113, 9)], 2.5)
    else:  # steam wisp squiggle upper-right
        c.d.arc([_s(98), _s(6), _s(110), _s(18)], 90, 270, fill=INK, width=_s(3))
        c.d.arc([_s(98), _s(17), _s(110), _s(29)], 270, 90, fill=INK, width=_s(3))


def raised_pad(c: Canvas):
    c.ellipse(72, 84, 92, 100)


def zzz(c: Canvas):
    for x, y, s in ((84, 36, 7), (96, 24, 9), (108, 8, 11)):
        c.line([(x, y), (x + s, y), (x, y + s), (x + s, y + s)], 2.5)


def sparkle(c: Canvas, cx=104, cy=18):
    c.poly([(cx, cy - 9), (cx + 2.2, cy - 2.2), (cx + 9, cy), (cx + 2.2, cy + 2.2),
            (cx, cy + 9), (cx - 2.2, cy + 2.2), (cx - 9, cy), (cx - 2.2, cy - 2.2)])
