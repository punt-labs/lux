"""Refactor check: the packaged RowBuilder paints the same grid as the spike's per-cell reader."""
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
import replay  # spike recordings
from ghostty_rows import GhosttyRows  # the straightforward per-cell reference
from pyghostty import Terminal

from punt_lux.display.terminal.render_state import RenderState


def paint(rows, cols):
    grid = [[(" ", None, None) for _ in range(cols + 2)] for _ in rows]
    for y, row in enumerate(rows):
        for b in row.bgs:
            for x in range(b.x, b.x + b.ncells):
                grid[y][x] = (grid[y][x][0], grid[y][x][1], b.color)
        for r in row.runs:
            chars = [r.text] if (r.wide or len(r.text) != r.ncells) else list(r.text)
            for i, ch in enumerate(chars):
                grid[y][r.x + i] = (ch, r.fg if ch != " " else None, grid[y][r.x + i][2])
    return grid


bad = 0
for name in ["vim", "top", "ls_color", "unicode", "truecolor", "cat_source", "showcase"]:
    rec = replay.load(name)
    t1, t2 = Terminal(rec.cols, rec.rows), Terminal(rec.cols, rec.rows)
    ref, new = GhosttyRows(t1), RenderState(t2)
    mism = 0
    for batch in replay.frames(rec, 256 * 1024, 400):
        t1.feed(batch); t2.feed(batch); ref.update(); new.update()
        if paint(ref.rows, rec.cols) != paint(new.rows, rec.cols):
            mism += 1
    print(f"{name:11} {'OK' if not mism else f'{mism} mismatched frames'}")
    bad += mism
sys.exit(1 if bad else 0)
