# Step 3: the terminal inside the real Lux display

**Answer: it works. Jim used it live: typing, scrolling and colours all work, and
it felt fast, on a machine that was overloaded at the time.**

## What was built (spike-only, branch `spike/terminal-ghostty`)

| Piece | Where |
|---|---|
| `terminal` element type: `id`, `session` (defaults to `id`), `command` (default: login shell), `height` (0 = fill) | `src/punt_lux/protocol/elements/terminal.py`, registered in `abc_leaf_kinds.py`, `abc_kind_names.py`, `elements/__init__.py` |
| ImGui renderer, using the step 2 widget | `src/punt_lux/display/renderers/imgui/terminal.py`, added to `factory.py` |
| Widget code (rows, fast rows, input, view) | `src/punt_lux/display/terminal/` (copied from `spikes/terminal/`) |
| Shell sessions owned by the Display: stand-in for `luxd-pty` | `src/punt_lux/display/terminal/sessions.py` |
| Pump every PTY once per frame; full speed while output flows | `render_loop.py` (`_pump_terminals`) |
| Monospace font + CJK/emoji fallbacks | `fonts.py` (`_load_terminal_font`) |
| `pyghostty==0.1.4` in the `display` extra | `pyproject.toml` |

Placed with an ordinary scene call; nothing in the Hub knows about terminals:

```json
{"elements": [{"kind": "terminal", "id": "term1", "session": "spike-shell", "command": "/bin/zsh -l"}],
 "frame": {"frame_id": "terminal-spike", "frame_title": "Terminal (spike)", "size": [1100, 700]}}
```

## How it was run: a second, isolated Lux

The spike ran beside Jim's real Lux without touching it:

- `HOME=/tmp/lux-spike-home`: separate hub state, port file and logs.
- `LUX_SOCKET=/tmp/lux-spike-run/display.sock`: separate display socket.
- `luxd-hub --port 8531`: separate hub port.

Commands are in `/tmp/lux-spike-env.sh`. Gotcha: both displays open their window at
the same position, so the spike's window sat exactly on top of the real one.

## Measured (live, `top` running in the terminal)

| | |
|---|---|
| Frame rate | 51.6 fps (27 fps idle: the wake-on-output fix works) |
| Display CPU | about 13.6% of one core |
| Display memory | 88 MB resident |
| Machine at the time | load average 11–25 on 8 cores (ethos, Bitdefender and a biff process each near 100%) |

## Keyboard conflicts: none found (from the code)

The Lux display takes no global keys. The only key handling outside the terminal is
Enter in `input_text` and Escape in a focused modal. Menu shortcuts are only shown
as labels, not bound to keys. So the terminal gets every key while it's focused.

## Bugs found and fixed

**Cursor about 10 px to the right, and columns not lining up (`ls -F`), found by Jim.**
Lux scales all text by 1.1 (`font_scale_main`), so Inconsolata is drawn at 15 px and
each character is 7.5 px wide. The widget measured the cell with
`calc_text_size("M")`, which rounds up to 8 px. ImGui drew the text at 7.5 px per
character, but the cursor and the start of each coloured run were placed on an 8 px
grid, adding 0.5 px of error per column. Fix: use the glyph's real advance
(`find_glyph("M").advance_x`). Jim confirmed both symptoms are gone. This matters for
the product: any font scale that isn't 1.0 would cause it.

**The Display hung on exit.**

Closing a session waited forever for the shell to exit (`os.waitpid(pid, 0)`). A
`zsh` that was in use didn't exit on hang-up, so the Display hung on shutdown. Now
`close()` sends SIGHUP, waits briefly without blocking, then sends SIGKILL. Tested:
closing a shell that ignores SIGHUP now takes 0.34 s.

## Known spike limitations (by design, for now)

- Shells live inside the Display process, so they die when it restarts. The
  separate `luxd-pty` daemon fixes this: step 4.
- Fallback font paths are macOS-only; Linux would use Noto.
- Emoji are still black and white; wide characters aren't exactly 2 cells.

## Still to measure

1. Frame time with a flooding terminal next to a 1,000-row table (DES-070 scale
   case). Held until the machine's load average is under 8, so the numbers reflect
   Lux, not the overload.
2. Focus moving between frames, and docking the terminal frame into a tab
   (by hand).
3. Typing through a Chinese or Japanese input method.

## Jim's verdict

"The terminal feels completely native. Very snappy. At least as snappy as kitty."

## Tests

Lux's full suite was not used as evidence here. On macOS it has known
environment-dependent failures and hangs, which the lux agent is fixing separately
(display-spawn hang, socketpair reset semantics, two timing-sensitive tests). The one
test the spike broke, which builds every element type with only an `id`, was fixed by
defaulting `session` to the `id`. Targeted run with a 30 s per-test timeout:
`tests/protocol` plus that test, 2,151 passed in 17.8 s. Lint and format pass across
the repo. mypy passes on the integration files. The widget package
`display/terminal/` is excluded from ruff on this branch as spike code.

## PTY throughput: two rounds of fixes

**Found by the flood-plus-table measurement.** Lux stayed fast: 95-112 fps
with a 1,000-row table and flooding terminals, and the table was the expensive
part (about 53% of one core on its own). But the terminals received only about
0.5 MB/s, and `yes` sat at 0% CPU. A heavy program ran far slower inside Lux
than in kitty.

**Cause.** A macOS PTY buffers only about 1 KB (measured: 1,024 bytes queued
whether we waited 0.5 ms or 5 ms). The original `pump()` read only what was
ready *at that instant*, about 1 KB, and returned. The program filled the
buffer, then blocked until the next frame. So throughput was capped near
1 KB per frame.

All numbers below come from separate runs, each under a hard `timeout`, with
the child killed in `finally` (no blocking `waitpid`). Machine load average
was 4-9 during these runs.

### Round 1: wait briefly for the refill (`pty.py`)

`pump()` now keeps reading for up to a time budget (2 ms). Once output is
flowing it waits up to 2 ms for the next refill instead of returning at once.
If nothing has arrived it doesn't wait at all, so an idle terminal still costs
nothing.

Isolated PTY strategies (`pty_throughput.py`, 60 fps loop, `yes` flood):

| Strategy | Throughput | Read time per frame |
|---|---|---|
| ready now (original) | 0.1 MB/s | 0.05 ms |
| keep reading, no wait | 0.1 MB/s | 0.07 ms |
| wait for refill, 1 ms budget | 4.7 MB/s | 1.0 ms |
| wait for refill, 2 ms budget | 8.1 MB/s | 2.0 ms |
| wait for refill, 4 ms budget | 19.4 MB/s | 4.0 ms |
| wait for refill, 8 ms budget | 69.6 MB/s | 8.0 ms |

The real `PtyProcess.pump`, before and after round 1:

| | Flood | Idle terminal |
|---|---|---|
| Before | 0.1 MB/s | 0.023 ms per frame |
| After round 1 | 6.0 MB/s, 2 ms per frame | 0.014 ms per frame |

Throughput scales with the time budget, so the budget is a straight trade
between flood speed and frame time.

### Round 2: one budget per frame, shared across terminals (`sessions.py`)

`pump_all()` now gives the whole frame one read budget of 6 ms, out of a
16.7 ms frame. It shares the budget out so that:

- quiet terminals go first and return at once;
- each terminal gets an equal share of the time *left*, so busy ones inherit
  what quiet ones didn't use;
- many floods together can't exceed the budget.

End to end (`TerminalSessions.pump_all` plus painting real Ghostty views in
headless ImGui, 60 fps loop):

| Scenario | Round 1 (2 ms each) | Round 2, first try (equal split) | Round 2, final (quiet first) |
|---|---|---|---|
| 1 flood | 6.0 MB/s | 45.5 MB/s, 7.8 ms/frame | 29.9-45.5 MB/s, 7.7 ms/frame |
| 2 floods | not measured | 32.8 MB/s, 7.8 ms/frame | 35.6 MB/s, 7.8 ms/frame |
| 1 flood + 3 idle | not measured | **4.8 MB/s** | **35.6 MB/s**, 7.9 ms/frame |
| 4 idle | not measured | 1.1 ms/frame | 0.8 ms/frame |

- The first round-2 try split the budget equally up front. A flood next to
  three idle terminals got only a quarter of it (4.8 MB/s). Scheduling quiet
  terminals first fixed that.
- The 1-flood result varies run to run (29.9-45.5 MB/s) with machine load.
- **Net: about 0.1 MB/s to 30-45 MB/s, roughly 300×**, with frame work held
  under about 8 ms p95, so 60 fps is kept.

### Still open

- kitty or Ghostty proper sustain hundreds of MB/s; at 30-45 MB/s a very
  large `cat` is still slower than in a native terminal. Further options:
  - a larger budget when only terminals are busy;
  - a reader thread that only queues bytes (Ghostty stays on the render
    thread). That conflicts with DES-002's no-threads rule and needs an ADR.
  - in `luxd-pty`, a separate process reads at full speed and sends to the
    Display, so this cap moves out of the render loop entirely.
- Not re-measured live in the Lux window after the fix (the spike display was
  shut down to stop the flood). The end-to-end headless bench uses the same
  code path.
