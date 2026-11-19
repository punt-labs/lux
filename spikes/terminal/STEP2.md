# Step 2: the widget in a plain imgui-bundle app

**Answer: it looks right and behaves right. Two real findings for Lux
(idle frame rate and fonts), one open item (color emoji).**

Same setup as Step 1 (M2, Python 3.13, imgui-bundle 1.92.900), now with a real
window: GLFW + OpenGL, hello_imgui `DarculaDarker` theme, `fps_idle = 30`, one
thread, a zero-wait read of the PTY once per frame. No Lux code involved.

## What was built

| File | What it is |
|---|---|
| `ghostty_view.py` | `GhosttyTerminalView`: same surface as `imgui_terminal.TerminalView` (`feed`, `on_input`, `on_resize`, `render_in_child`, `title`). Rendering, cursor styles, selection, scrollback, wheel, copy and paste. |
| `ghostty_input.py` | ImGui keys, text, mouse and paste turned into bytes by Ghostty's own encoders. |
| `transport.py` | `LocalPtyTransport` (no reader thread; reads at most 256 KB per frame) and `ReplayTransport`. |
| `demo.py` | Side-by-side or single-pane app: live shell, a command, or a replayed recording. |
| `live_test.py`, `live_apps.py` | Scripted live tests: real programs in a PTY, driven through the widget's real input path. |

## Looks right

- Screenshots of each engine alone, same layout, same theme and palette:
  **vim and top are pixel-identical to the pyte widget** (`compare_shots.py`: 0/58 rows differ).
- `ls_color` differs on purpose: pyte doesn't follow `ls -G` colors correctly, Ghostty does.
- Render cost in the real window, Ghostty vs pyte (p50): top 0.3 vs 10 ms, vim 0.3 vs 17 ms,
  colored ls 3 vs 16 ms.

## Behaves right (15/15 live checks)

Shell (bash): typing, Enter, Ctrl-C, arrows (`cat -v` shows `^[[A`), paste, line wrap,
resize reaching the PTY (`$COLUMNS x $LINES` matches the widget), shell exit detected.

vim: draws, turns on mouse tracking, Shift keys (`G`), **mouse click moves vim's cursor**,
**bracketed paste** (multi-line paste lands intact), `:q!` exits.
top: renders, `q` quits.

Key encoding spot checks: `a`, `A`, Ctrl-C → `\x03`, Up → `\x1b[A`, and `\x1bOA` once the
program enables cursor-key application mode. Paste with mode 2004 off: newlines become CR
and an embedded `ESC[201~` is neutralized. SGR mouse: `\x1b[<0;3;3M`.

## Finding 1: idle frame rate (matters for Lux)

hello_imgui only stays at full speed for 3 s after **user input**. Program output does not
count, so a busy terminal in an untouched window updates at the idle rate:

| Window untouched, shell printing every 50 ms | frame interval p50 |
|---|---|
| Lux's current settings (`fps_idle = 30`) | 36.6 ms (about 27 fps) |
| With "wake on output" (switch idling off while bytes arrive, back on after 0.25 s quiet) | **8.9 ms** |
| Wake on output, then quiet | 37 ms (idle again, as it should be) |

Fix: one flag in the frame loop (`fps_idling.enable_idling`). Lux will need the same.

## Finding 2: fonts

- The fonts Lux has today (DejaVu) plus a monospace font cover Latin, box drawing and arrows,
  but are **missing all 24** CJK, Hangul and emoji characters in the test sample.
- Merging system fallbacks (Hiragino, Apple SD Gothic Neo, Arial Unicode, Apple Color Emoji)
  covers **all of them** (`check_glyphs.py`).
- Two width problems remain: CJK glyphs are 2.14 cells wide, Hangul 1.57 and emoji 1.79,
  instead of exactly 2. Wide characters need to be scaled or centered into 2 cells.
- Loading the fallbacks through `hello_imgui.load_font(merge_to_last_font=True)` did not take
  effect. Adding them directly to the ImGui font atlas did.
- On Linux these would be Noto CJK and Noto Color Emoji.

## Open: color emoji

Emoji draw as **monochrome** outlines, not color. FreeType is present (version 2.13.3), and
setting `LoadColor` and `Bitmap` didn't help with Apple's bitmap emoji font. Not yet tried:
a COLR or CBDT font such as Noto Color Emoji, and whether imgui-bundle's FreeType build
supports colour bitmaps. It doesn't block a terminal, but it's visible.

## Not done in step 2

- Typing in Chinese or Japanese (input methods) wasn't tested; only plain typing was.
- Lux's own frame cost next to a terminal, focus between frames, docking: step 3.
- Selection was tested in code (Ghostty selection, word and line via its API), not by dragging.

## Follow-up: pane extent (after the long demo)

- Jim noticed the pyte pane looked like a bigger active area, with its cursor near the
  bottom-right. Cause: pyte paints its whole child window and stacks scrollback above the
  live screen, pushing the 60-row grid and cursor down. Ghostty drew only its grid and
  left the rest as window background.
- Fix: `GhosttyTerminalView` now paints its whole child with the terminal background.
  The demo fits replays to the pane unless `--fixed` is passed (as live use does).
- Measured after the fix: both panes' terminal background covers 97% of the window height.
