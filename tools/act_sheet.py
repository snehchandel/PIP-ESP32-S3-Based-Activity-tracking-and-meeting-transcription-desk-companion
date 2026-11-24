"""Contact sheets of PIP's acts: `sim_rlcd --render-acts artifacts/rlcd_acts` then this script.
Each row = one act, 4 frames of PIP's stage: the whole world for the idle library, the left column for the
others (+ a sheet of the weather icons)."""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "artifacts/rlcd_acts/acts"
OUT = ROOT / "artifacts/rlcd_acts"
CROP = (0, 34, 152, 264)  # stage column
WORLD = (0, 34, 400, 264)  # idle: PIP roams the whole screen


def main() -> int:
    rows: dict[str, list[Path]] = defaultdict(list)
    for p in sorted(SRC.glob("*.png")):
        m = re.match(r"(\d+_\w+?)__(\d+_.+?)__(\d)\.png", p.name)
        if m:
            rows[f"{m.group(1)}/{m.group(2)}"].append(p)
    by_mode: dict[str, list[str]] = defaultdict(list)
    for k in rows:
        by_mode[k.split("/")[0]].append(k)
    for mode, keys in by_mode.items():
        crop = WORLD if mode.endswith("_idle") else CROP
        cw, ch = crop[2] - crop[0], crop[3] - crop[1]
        sheet = Image.new("L", (130 + 4 * (cw + 6), len(keys) * (ch + 8)), 255)
        d = ImageDraw.Draw(sheet)
        for r, k in enumerate(keys):
            y = r * (ch + 8)
            d.text((4, y + ch // 2), k.split("/")[1].split("_", 1)[1][:20], fill=0)
            for c, p in enumerate(rows[k][:4]):
                sheet.paste(Image.open(p).convert("L").crop(crop), (130 + c * (cw + 6), y))
        sheet.save(OUT / f"sheet_{mode}.png")
        print("wrote", OUT / f"sheet_{mode}.png", len(keys), "acts")
    w = sorted(SRC.glob("weather_*.png"))
    if w:
        sheet = Image.new("L", (len(w) * 130, 40), 255)
        for i, p in enumerate(w):
            sheet.paste(Image.open(p).convert("L").crop((270, 0, 400, 40)), (i * 130, 0))
        sheet = sheet.resize((sheet.width * 2, sheet.height * 2), Image.NEAREST)
        sheet.save(OUT / "sheet_weather.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
