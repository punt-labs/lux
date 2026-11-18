# Architecture Decision Records: Lux terminal (spike)

These ADRs record decisions made while spiking a terminal for the Lux display
on branch `spike/terminal-ghostty`. They are **spike records**, not accepted
Lux architecture. Lux's settled decisions live in
[`DESIGN.md`](../../DESIGN.md) as `DES-NNN` entries; if this work is adopted,
these should become new `DES` entries there.

Evidence is in `spikes/terminal/STEP1.md` through `STEP4-PLAN.md`, with
actual-window and measured results in `STEP4-LIVE.md` and `STEP4-PERFORMANCE.md`.
Code spans `src/punt_lux/display/terminal/`, `terminal/`, `ptyd/` and
`protocol/pty/`. What a polished product still
needs is in [`../terminal-known-limitations.md`](../terminal-known-limitations.md).

| ADR | Decision | Status |
| --- | --- | --- |
| [0001](0001-terminal-engine-libghostty-vt.md) | Use libghostty-vt as the terminal engine, not pyte | Accepted (spike) |
| [0002](0002-python-binding-pyghostty.md) | Bind it with pyghostty, pinned exactly, behind one module | Accepted (spike) |
| [0003](0003-bulk-row-decode.md) | Rebuild only dirty rows; decode each row in bulk with numpy | Accepted (spike) |
| [0004](0004-input-through-ghostty-encoders.md) | Turn all input into bytes with Ghostty's encoders | Accepted (spike) |
| [0005](0005-cell-geometry-from-glyph-advance.md) | Measure the cell from the glyph advance, not `calc_text_size` | Accepted (spike) |
| [0006](0006-terminal-element-and-sessions.md) | A `terminal` element names a session; the Display pumps sessions each frame | Superseded by ADR-0007 (element schema remains) |
| [0007](0007-independent-terminal-owner-and-replicas.md) | Independent owner, replaceable replicas, credit/reset and lazy lifecycle | Accepted (spike), not merge approval |

Each record has Context, Decision, Consequences and Alternatives.
