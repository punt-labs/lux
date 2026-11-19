"""Load a recording and slice it into per-frame byte batches.

A frame is 1/60 s of recorded time. Each frame takes at most `budget` bytes;
anything over the budget carries into the next frame (as a real display loop
with a per-frame read cap would behave under a flood).
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

FRAME_S = 1 / 60
RECORDINGS = Path(__file__).parent / "recordings"


@dataclass(frozen=True, slots=True)
class Recording:
    name: str
    cols: int
    rows: int
    chunks: list[tuple[float, bytes]]

    @property
    def total_bytes(self) -> int:
        return sum(len(d) for _, d in self.chunks)


def load(name: str) -> Recording:
    lines = (RECORDINGS / f"{name}.jsonl").read_text().splitlines()
    head = json.loads(lines[0])
    chunks = [(t, base64.b64decode(b)) for t, b in map(json.loads, lines[1:])]
    return Recording(name, head["cols"], head["rows"], chunks)


def frames(rec: Recording, budget: int, max_frames: int | None = None) -> Iterator[bytes]:
    """Yield one byte batch per frame (possibly empty), until all bytes are consumed."""
    pending = bytearray()
    i, n, frame = 0, len(rec.chunks), 0
    while i < n or pending:
        t_end = (frame + 1) * FRAME_S
        while i < n and rec.chunks[i][0] < t_end:
            pending += rec.chunks[i][1]
            i += 1
        batch = bytes(pending[:budget])
        del pending[:budget]
        yield batch
        frame += 1
        if max_frames is not None and frame >= max_frames:
            return
