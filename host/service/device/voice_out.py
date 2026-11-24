"""Stream Piper speech to the PIP speaker as AUDIO_START_OUT / AUDIO_DATA_OUT / AUDIO_END_OUT frames.

The device buffers ~1 s (32 KB), so frames are paced at real time with a 0.5 s lead."""
from __future__ import annotations

import asyncio
import struct
from typing import TYPE_CHECKING

import numpy as np

from ..protocol import FrameType

if TYPE_CHECKING:
    from .link import DeviceLink

CHUNK_SAMPLES = 320          # 20 ms at 16 kHz, 640 bytes
LEAD_CHUNKS = 25             # 0.5 s pre-fill
_stream_id = 0


async def speak_on_device(link: DeviceLink, pcm: np.ndarray) -> bool:
    global _stream_id
    if not link.linked or pcm.size == 0:
        return False
    _stream_id = (_stream_id + 1) & 0xFFFFFFFF
    sid = _stream_id
    total = int(pcm.size) * 2
    if not link.send(FrameType.AUDIO_START_OUT, struct.pack("<IHBBI", sid, 16000, 1, 16, total), ack=True):
        return False
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    data = pcm.astype("<i2").tobytes()
    for i, off in enumerate(range(0, len(data), CHUNK_SAMPLES * 2)):
        due = t0 + max(0, i - LEAD_CHUNKS) * 0.02
        delay = due - loop.time()
        if delay > 0:
            await asyncio.sleep(delay)
        if not link.send(FrameType.AUDIO_DATA_OUT, struct.pack("<IH", sid, i & 0xFFFF) + data[off: off + CHUNK_SAMPLES * 2]):
            return False
    link.send(FrameType.AUDIO_END_OUT, struct.pack("<IBBBB", sid, 0, 0, 0, 0), ack=True)
    return True
