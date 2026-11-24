"""Loop A, step 1: automated pixel & layout gate for the 1-bit RLCD (spec 9.1).

  python tools/verify_rlcd.py --strict [--update-golden]

Checks every artifacts/rlcd/raw/*.png (+ meta JSON) and the 8 PIP sprites, writes warm bezel previews
to artifacts/rlcd/preview/, and diffs against tests/golden/rlcd/ baselines."""
from __future__ import annotations

import argparse
import itertools
import json
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
RAW, META, PREVIEW = ROOT / "artifacts/rlcd/raw", ROOT / "artifacts/rlcd/meta", ROOT / "artifacts/rlcd/preview"
GOLDEN = ROOT / "tests/golden/rlcd"
SPRITES = ROOT / "artifacts/pip/png"
EXPECTED_SCREENS = 13
EXPRESSIONS = ["ready", "listening", "thinking", "working", "paused", "done", "alarm", "sleep"]


def black(img: Image.Image) -> list[list[bool]]:
    px = img.convert("L").load()
    return [[px[x, y] < 128 for x in range(img.width)] for y in range(img.height)]


def ratio(b: list[list[bool]], x0: int, y0: int, x1: int, y1: int) -> float:
    cells = [b[y][x] for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]
    return sum(cells) / len(cells)


def overlaps(meta: dict) -> list[str]:  # type: ignore[type-arg]
    boxes = meta["boxes"]
    bad = []
    for (i, a), (j, b) in itertools.combinations(enumerate(boxes), 2):
        if a["parent"] == j or b["parent"] == i:
            continue  # nested inside the other box
        if a["parent"] != b["parent"]:
            continue  # only siblings (same container, or both top-level) must not collide
        ax1, ay1, bx1, by1 = a["x"] + a["w"], a["y"] + a["h"], b["x"] + b["w"], b["y"] + b["h"]
        if a["x"] < bx1 and b["x"] < ax1 and a["y"] < by1 and b["y"] < ay1:
            bad.append(f"{a['name']} x {b['name']}")
    return bad


def check_screen(path: Path, strict_meta: bool = True) -> list[str]:
    img = Image.open(path)
    errs: list[str] = []
    if img.size != (400, 300):
        return [f"size {img.size}"]
    colors = {c for _, c in img.convert("L").getcolors(1 << 16) or []}
    if not colors <= {0, 255}:
        errs.append(f"gray pixels present {sorted(colors)[:5]}")
    b = black(img)
    margin = [(x, y) for y in range(0, 264) for x in (*range(0, 4), *range(396, 400)) if b[y][x]]
    margin += [(x, y) for y in range(0, 4) for x in range(400) if b[y][x]]
    if margin:
        errs.append(f"{len(margin)} ink pixels inside the 4 px safe margin, e.g. {margin[0]}")
    ink = ratio(b, 0, 0, 399, 263)
    if not 0.06 <= ink <= 0.42:  # floor lowered 8%->6% for the smaller task text (ADR-014)
        errs.append(f"canvas ink {ink:.1%} outside 6-42%")
    bar_black = ratio(b, 0, 264, 399, 299)
    if bar_black < 0.70 or (1 - bar_black) < 0.03:
        errs.append(f"status bar black {bar_black:.1%} (need >=70% black, >=3% white)")
    stage = ratio(b, 16, 70, 135, 189)  # mascot region (MASCOT_Y = 70)
    if not 0.12 <= stage <= 0.60:
        errs.append(f"mascot stage ink {stage:.1%} outside 12-60%")
    meta_path = META / f"{path.stem}.json"
    if strict_meta:
        if not meta_path.exists():
            errs.append("missing meta json")
        else:
            bad = overlaps(json.loads(meta_path.read_text()))
            if bad:
                errs.append("overlapping boxes: " + ", ".join(bad))
    return errs


def check_sprites() -> list[str]:
    errs, masks = [], {}
    for name in EXPRESSIONS:
        img = Image.open(SPRITES / f"{name}.png")
        if img.size != (120, 120) or img.mode != "1":
            errs.append(f"sprite {name}: {img.size} {img.mode}")
            continue
        b = black(img)
        masks[name] = b
        ink = ratio(b, 0, 0, 119, 119)
        if not 0.12 <= ink <= 0.60:
            errs.append(f"sprite {name}: ink {ink:.1%}")
    for a, c in itertools.combinations(masks, 2):  # distinguishable at arm's length
        diff = sum(masks[a][y][x] != masks[c][y][x] for y in range(120) for x in range(120)) / 14400
        if diff < 0.03:
            errs.append(f"sprites {a}/{c} differ by only {diff:.1%}")
    return errs


def golden_diff(path: Path) -> float | None:
    g = GOLDEN / path.name
    if not g.exists():
        return None
    a, b = black(Image.open(path)), black(Image.open(g))
    return sum(a[y][x] != b[y][x] for y in range(300) for x in range(400)) / 120000


def preview(path: Path) -> None:
    """Warm reflective-LCD look: paper-tinted panel, soft ink, orange bezel (as on the real board)."""
    src = Image.open(path).convert("L").resize((800, 600), Image.NEAREST)
    panel = Image.new("RGB", src.size, (217, 214, 204))
    panel.paste((28, 28, 30), mask=src.point(lambda v: 255 if v < 128 else 0))
    out = Image.new("RGB", (800 + 96, 600 + 96), (233, 138, 44))
    d = ImageDraw.Draw(out)
    d.rounded_rectangle([20, 20, 800 + 76, 600 + 76], radius=26, fill=(24, 24, 27))
    out.paste(panel, (48, 48))
    PREVIEW.mkdir(parents=True, exist_ok=True)
    out.save(PREVIEW / path.name)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--update-golden", action="store_true")
    args = ap.parse_args()
    screens = sorted(RAW.glob("*.png"))
    failures: list[str] = []
    if args.strict and len(screens) != EXPECTED_SCREENS:
        failures.append(f"expected {EXPECTED_SCREENS} screens, found {len(screens)}")
    for s in screens:
        errs = check_screen(s)
        d = golden_diff(s)
        if d is not None and d > 0.005:
            errs.append(f"golden diff {d:.2%} > 0.5%")
        preview(s)
        print(f"{'PASS' if not errs else 'FAIL'} {s.stem}" + ("" if d is None else f" (golden diff {d:.3%})"))
        failures += [f"{s.stem}: {e}" for e in errs]
    for e in check_sprites():
        failures.append(e)
    print(f"sprites: {'PASS' if not any(f.startswith('sprite') for f in failures) else 'FAIL'} (8 expressions)")
    for hw in sorted((ROOT / "artifacts/rlcd/hardware").glob("hw_*.png")):
        errs = check_screen(hw, strict_meta=False)
        print(f"{'PASS' if not errs else 'FAIL'} hardware/{hw.stem}")
        failures += [f"hardware/{hw.stem}: {e}" for e in errs]
    if args.update_golden and not failures:
        GOLDEN.mkdir(parents=True, exist_ok=True)
        for s in screens:
            shutil.copy(s, GOLDEN / s.name)
        print(f"golden baselines updated ({len(screens)})")
    for f in failures:
        print("  -", f)
    print(f"verify_rlcd: {'PASS' if not failures else 'FAIL'} ({len(screens)} screens, 8 expressions)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
