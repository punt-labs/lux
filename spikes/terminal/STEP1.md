# Step 1: is Python fast enough? (headless, no Lux)

**Answer: yes, with one design choice and one known worst case.**

Machine: Apple M2, Python 3.13.1, pyghostty 0.1.4, imgui-bundle 1.92.900.
Terminal 200×60. Real ImGui frames (headless context, Inconsolata 15 px),
so draw-list cost is measured, not estimated. Raw table: `results_step1.txt`.

## Results (Python time per frame, p50 / p95, ms)

| Recording | pyte widget (today) | Ghostty, per-cell | **Ghostty, bulk rows** |
|---|---|---|---|
| vim (startup, syntax) | 7.1 / 10.9 | 0.1 / 8.4 | **0.1 / 0.9** |
| top (1 Hz refresh) | 6.0 / 12.8 | 0.1 / 0.2 | **0.1 / 0.1** |
| `ls -laGR` colored | 16 / 77 | 11 / 16 | **1.0 / 1.5** |
| CJK + emoji | 9.6 / 11.0 | 10 / 11 | **2.9 / 4.0** |
| `cat` 4 MB source | 524 / 796 | 9.4 / 9.8 | **1.4 / 2.9** |
| `yes` flood, 21 MB | 1036 / 1689 | 11 / 17 | **1.2 / 1.3** |
| 24-bit color, every cell different | 21 / 32 | 3.9 / 22 | 3.8 / **30** |

Parse throughput: pyte 0.2–1.5 MB/s, Ghostty 300–720 MB/s (~1000×).
Full redraw (every row rebuilt): vim 0.9 ms, top 1.0 ms, cat 1.2 ms. Idle frame: 0.03–0.06 ms.

## Criteria from the plan

| Criterion | Target | Result |
|---|---|---|
| Typical frame | < 2 ms | ✅ 0.1 ms |
| Full redraw | < 8 ms | ✅ ~1 ms on normal content, ❌ 37 ms on the per-cell-truecolor stress test |
| Flood stays responsive | bounded | ✅ 1.3 ms p95 at 256 KB/frame (2.4 ms at 1 MB/frame) |
| Fidelity | — | Headless only: bulk builder output matches the per-cell builder on all recordings (`check_fast.py`) |

## What made it fast

1. **Dirty rows only** (Ghostty's render state). An idle or mostly-idle terminal costs almost nothing.
2. **Bulk row read.** One FFI call per row gets all 200 packed cells
   (`GHOSTTY_RENDER_STATE_ROW_DATA_CELLS_RAW`), decoded with numpy. Bit positions come
   from `ghostty_type_json()` at startup, as the header requires. Per-cell FFI calls
   remain only for the first cell of each style, grapheme clusters, and wide cells.
   This is 5–10× faster than the per-cell iteration tilix2 uses.
3. **Feed is negligible.** Ghostty parses in C. pyte's parser alone takes 0.5–1 s per frame under a flood.

## The worst case

A screen where every cell has its own color (a 24-bit gradient) costs ~37 ms to
rebuild in full, because each distinct style costs a few FFI calls. Real programs
rarely do this (image-to-ANSI viewers, some btop themes). Fixes, cheapest first:
cache styles by value rather than per row; read styles through a bulk call if
pyghostty exposes one; move `_build_mixed` into a small C/Cython helper. Not needed
to proceed.

## Not yet measured (steps 2–3)

- GPU-side cost and real swap time (headless here).
- Input latency, Lux's 30 fps idle throttling, focus, fonts for emoji/CJK.
- Lux's own per-frame cost next to a terminal.

## Notes

- `numpy` is already in Lux's `[display]` extra.
- pyghostty must stay pinned exactly: we use its private `_ffi` layer.
- `record.py` captures real programs through a PTY; `bench.py` replays them;
  `check_fast.py` verifies the bulk builder against the per-cell one.
