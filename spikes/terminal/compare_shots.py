"""Compare per-engine screenshots (shots/NAME_ghostty.png vs shots/NAME_pyte.png) by text row."""

from __future__ import annotations

import sys

import numpy as np
from PIL import Image


def load(path: str) -> np.ndarray:
    a = np.asarray(Image.open(path).convert("RGB")).astype(np.int16)
    return a[int(a.shape[0] * 0.06) :]


for name in sys.argv[1:]:
    g, p = load(f"shots/{name}_ghostty.png"), load(f"shots/{name}_pyte.png")
    bg = np.array([30, 30, 30])
    ig = np.abs(g - bg).sum(-1) > 60
    ip = np.abs(p - bg).sum(-1) > 60
    diff = np.abs(g - p).sum(-1) > 60
    # rows of text: 2x scale, 15px font -> ~32px per row
    rows = [(y, ig[y : y + 32].mean(), ip[y : y + 32].mean(), diff[y : y + 32].mean())
            for y in range(0, g.shape[0] - 32, 32)]  # fmt: skip
    bad = [(i, a, b, d) for i, (_, a, b, d) in enumerate(rows) if d > 0.02]
    print(f"{name:9} ink g {ig.mean():.3f} p {ip.mean():.3f}  pixel diff {diff.mean():.3f}  "
          f"rows differing {len(bad)}/{len(rows)}")  # fmt: skip
    for i, a, b, d in bad[:6]:
        print(f"   row {i:2d}: ink g {a:.3f} p {b:.3f} diff {d:.3f}")
