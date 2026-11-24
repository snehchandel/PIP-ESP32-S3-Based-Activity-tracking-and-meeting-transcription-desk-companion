"""Convert the 15,000-byte logical framebuffer (1 = black, MSB-first) to/from PNG."""
from __future__ import annotations

import io

from PIL import Image

from .frames import FB_BYTES

W, H = 400, 300


def fb_to_image(fb: bytes) -> Image.Image:
    if len(fb) != FB_BYTES:
        raise ValueError(f"framebuffer must be {FB_BYTES} bytes, got {len(fb)}")
    # PIL mode "1" packs 1 = white; the device packs 1 = black ink.
    return Image.frombytes("1", (W, H), bytes(b ^ 0xFF for b in fb))


def fb_to_png(fb: bytes) -> bytes:
    out = io.BytesIO()
    fb_to_image(fb).save(out, format="PNG")
    return out.getvalue()


def image_to_fb(img: Image.Image) -> bytes:
    if img.size != (W, H):
        raise ValueError("image must be 400x300")
    return bytes(b ^ 0xFF for b in img.convert("1").tobytes())
