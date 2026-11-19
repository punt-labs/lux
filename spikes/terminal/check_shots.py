"""Check step-2 screenshots without looking at them.

For each shot: split into the ghostty (left) and pyte (right) panes and report
how much ink each pane has, how many distinct colors, and how different they
are. Then check which codepoints in the unicode recording the loaded fonts
cannot draw (ImGui would render them as the fallback glyph).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

SHOTS = Path(__file__).parent / "shots"


def pane_stats(a: np.ndarray) -> tuple[float, int]:
    bg = np.median(a[::8, ::8].reshape(-1, a.shape[-1]), axis=0)
    ink = (np.abs(a.astype(int) - bg.astype(int)).sum(axis=-1) > 60).mean()
    q = (a[::4, ::4, :3] // 16).astype(np.int32)
    colors = len(np.unique(q[..., 0] * 256 + q[..., 1] * 16 + q[..., 2]))
    return float(ink), colors


def main() -> None:
    names = sys.argv[1:] or sorted(p.stem for p in SHOTS.glob("*.png"))
    print(f"{'shot':10} {'ink L':>6} {'ink R':>6} {'colors L':>8} {'colors R':>8} {'diff':>6}")
    for n in names:
        img = np.asarray(Image.open(SHOTS / f"{n}.png").convert("RGB"))
        h, w, _ = img.shape
        top = int(h * 0.06)  # skip the header text lines
        left, right = img[top:, : w // 2 - 8], img[top:, w // 2 + 8 :]
        m = min(left.shape[1], right.shape[1])
        left, right = left[:, :m], right[:, :m]
        (il, cl), (ir, cr) = pane_stats(left), pane_stats(right)
        diff = (np.abs(left.astype(int) - right.astype(int)).sum(axis=-1) > 60).mean()
        print(f"{n:10} {il:6.3f} {ir:6.3f} {cl:8d} {cr:8d} {diff:6.3f}")


if __name__ == "__main__":
    main()
