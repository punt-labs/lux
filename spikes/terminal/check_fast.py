"""Correctness: FastGhosttyRows must paint the same grid as GhosttyRows on every recording."""

from __future__ import annotations

import sys

from pyghostty import Terminal

import replay
from fast_rows import FastGhosttyRows
from ghostty_rows import GhosttyRows, Row

Cell = tuple[str, object, object]


def paint(rows: list[Row], cols: int) -> list[list[Cell]]:
    grid: list[list[Cell]] = [[(" ", None, None) for _ in range(cols + 2)] for _ in rows]
    for y, row in enumerate(rows):
        for b in row.bgs:
            for x in range(b.x, b.x + b.ncells):
                grid[y][x] = (grid[y][x][0], grid[y][x][1], b.color)
        for r in row.runs:
            chars = [r.text] if (r.wide or len(r.text) != r.ncells) else list(r.text)
            for i, ch in enumerate(chars):
                x = r.x + i
                fg = r.fg if ch != " " else None
                grid[y][x] = (ch, fg, grid[y][x][2])
    return grid


bad = 0
for name in sys.argv[1:] or ["vim", "top", "ls_color", "unicode", "truecolor", "cat_source"]:
    rec = replay.load(name)
    t1, t2 = Terminal(rec.cols, rec.rows), Terminal(rec.cols, rec.rows)
    slow, fast = GhosttyRows(t1), FastGhosttyRows(t2)
    mism = 0
    for i, batch in enumerate(replay.frames(rec, 256 * 1024, 400)):
        t1.feed(batch)
        t2.feed(batch)
        slow.update()
        fast.update()
        a, b = paint(slow.rows, rec.cols), paint(fast.rows, rec.cols)
        if a != b:
            mism += 1
            if mism == 1:
                for y, (ra, rb) in enumerate(zip(a, b, strict=True)):
                    if ra != rb:
                        x = next(x for x in range(len(ra)) if ra[x] != rb[x])
                        print(f"  {name} frame {i} row {y} col {x}: slow={ra[x]} fast={rb[x]}")
                        break
    print(f"{name:11} {'OK' if not mism else f'{mism} mismatched frames'}")
    bad += mism
sys.exit(1 if bad else 0)
