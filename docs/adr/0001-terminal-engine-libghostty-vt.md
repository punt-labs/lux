# ADR-0001: Use libghostty-vt as the terminal engine, not pyte

- **Status:** Accepted (spike)
- **Date:** 2026-11-15
- **Evidence:** `spikes/terminal/STEP1.md`, `STEP2.md`, `STEP3.md`

## Context

Lux wants a terminal inside its display, next to its other elements. The Vox
Rooms notes name terminals as the entry fee for competing with herdr and say a
native VT parser such as libghostty-vt is "probably required".

imgui-bundle, which Lux already uses, ships a terminal widget
(`imgui_bundle.imgui_terminal`). Its design is good: a widget that draws and
handles keys, separate from a transport that supplies bytes. But its engine is
**pyte**, a pure-Python VT emulator. pyte is slow, only partly xterm-compatible,
and its widget does no dirty tracking: it rebuilds every visible cell every
frame.

The engine has to keep up with real programs inside a single-threaded Python
render loop (DES-002), on a machine that is often busy.

## Decision

Use **libghostty-vt**, the terminal core of Ghostty, as the engine. Keep
imgui_terminal's *shape* (widget plus transport, same public surface), so the
two are interchangeable.

## Consequences

Measured at 200×60 on an Apple M2 with Python 3.13:

| | pyte widget | Ghostty widget |
|---|---|---|
| Parse throughput | 0.2–1.5 MB/s | 300–720 MB/s |
| `yes` flood, Python time per frame (p50) | 1,036 ms | 1.2 ms |
| `vim` / `top`, render per frame (real window) | 17 / 10 ms | 0.3 / 0.3 ms |
| Fidelity | wrong `ls -G` colours | pixel-identical on `vim`/`top`; correct `ls` colours |

- Ghostty also provides what a good terminal needs and pyte doesn't:
  - dirty-row render state
  - key, mouse and paste encoders (ADR-0004)
  - selection that follows scrolling
  - kitty keyboard and graphics protocols
  - reflow on resize
  - whole-terminal snapshots, which step 4 needs
- Jim, using it live inside Lux: "completely native… at least as snappy as
  kitty". Typing, scrolling, colours, two terminals at once, and docking all
  work.
- **Cost:** a native library dependency and a young Python binding (ADR-0002).
  libghostty-vt is MIT-licensed, with a stable C ABI from 1.0.

## Alternatives considered

- **pyte, the status quo:** rejected on speed and fidelity (table above).
- **xterm.js in a web view:** excellent, but runs out of process and doesn't
  draw through ImGui.
- **QTermWidget or VTE:** Qt/GTK widgets; they don't fit an ImGui display
  (DES-001 rejected Qt).
- **libvterm or alacritty_terminal:** viable cores. Ghostty has the most
  complete features and a documented embedding API, and the Vox Rooms notes
  already point at it.
