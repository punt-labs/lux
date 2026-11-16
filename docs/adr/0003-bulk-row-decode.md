# ADR-0003: Rebuild only dirty rows, decoding each row in bulk with numpy

- **Status:** Accepted (spike)
- **Date:** 2026-11-15
- **Evidence:** `spikes/terminal/STEP1.md`, `results_step1.txt`, `check_fast.py`;
  `src/punt_lux/display/terminal/row_builder.py`, `render_state.py`

## Context

Python draws the terminal every frame, so the cost per frame decides whether
this works at all. The straightforward reader (as in tilix2) walks each row
cell by cell, with several FFI calls per cell. On a 200×60 grid a full redraw
took about 10 ms for colored `ls`, 17 ms for CJK, and 37 ms when every cell
had its own colour.

## Decision

1. **Dirty rows only.** Ghostty's render state marks which rows changed.
   `RenderState.update()` rebuilds only those into cached `Row`s (text runs
   plus background spans). An idle terminal costs a few calls per frame.
2. **One FFI call per row.** `GHOSTTY_RENDER_STATE_ROW_DATA_CELLS_RAW` returns
   the whole row as packed 64-bit cells. numpy extracts every cell's code
   point, style id, wide flag and content tag in one pass.
3. **Plain rows** (no styles, wide cells or grapheme clusters; most shell
   output) become one run with no further calls.
4. **Mixed rows** are split at style changes and special cells. Per-cell calls
   remain only for:
   - the first cell of each style (cached per row; style ids are page-local)
   - grapheme clusters and wide cells
   - background-only cells
5. **Bit positions come from the library's manifest** (`cell_layout.py`), as
   libghostty-vt requires; they aren't ABI-stable.

## Consequences

Python time per frame at 200×60:

| Recording | Per-cell reader | Bulk reader |
|---|---|---|
| colored `ls` | 11 ms | 1.0 ms |
| `cat` of 4 MB | 9.4 ms | 1.4 ms |
| `yes` flood | 11 ms | 1.2 ms |

- A full redraw of normal content takes about 1 ms; an idle frame 0.03–0.06 ms.
- **Correctness:** compared with the per-cell reader on every recording
  (CJK, emoji, ZWJ sequences, 24-bit colour), before and after the refactor.
  The painted grids are identical.
- numpy is required; it is already in Lux's `display` extra.
- **Worst case still slow:** when every cell has a different style (a 24-bit
  gradient), a full rebuild costs about 37 ms. Fix if needed: cache styles by
  value across rows, or move `_build_mixed` into C.

## Alternatives considered

- **Per-cell reads (tilix2):** correct, but 5–10× slower.
- **A C/Cython row builder:** would also fix the worst case, but adds a build
  step (ADR-0002). Deferred until a real workload needs it.
- **Redraw everything every frame (pyte widget):** why that widget costs
  7–20 ms per frame even when nothing changes.
