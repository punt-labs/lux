# Lux terminal: known limitations and the path to a polished product

What the spike (`spike/terminal-ghostty`) deliberately did not do, or did only
partly. The spike answered the risky question: a libghostty-vt terminal works
inside the Lux display and feels native ("at least as snappy as kitty"). This
list covers everything else a shipping terminal needs.

**Priority:** P0 blocks shipping; P1 is expected by users of any good
terminal; P2 is polish.

**Status:** *missing* (not started), *partial* (works but incomplete),
*fixed* (found and fixed during the spike).

## 1. Sessions and lifecycle

| # | Limitation | Pri | Status | Notes |
|---|---|---|---|---|
| 1.1 | Shells die when the Display restarts (crash, upgrade, `lux display stop`) | P0 | missing | Step 4: a `luxd-pty` daemon that owns the PTYs and sends snapshot + bytes on attach (ADR-0006). |
| 1.2 | No session ownership or cleanup policy: who may start a session, and whether it ends when its scene is cleared | P0 | missing | Today a session lives until the Display exits. |
| 1.3 | No security model for `command` | P0 | missing | Any client that can show a scene can start any program as the user. Needs a consent gate like DES-004's code-running consent, or an allow-list. |
| 1.4 | `exit` respawned the shell | P0 | fixed | Now shows `[process exited]`; the frame stays until closed. |
| 1.5 | No "restart" or "close" action on an exited terminal | P1 | missing | e.g. a menu item or "press Enter to restart". |
| 1.6 | The Display hung on exit with a live shell | P0 | fixed | Non-blocking close: SIGHUP, short wait, then SIGKILL. |
| 1.7 | No working directory, environment or shell choice | P1 | missing | e.g. `cwd`, `env`, a per-repo default shell. |
| 1.8 | Exit status isn't reported | P2 | missing | Show it, and send an interaction event an agent can read. |
| 1.9 | No agent API to read the screen or send input | P1 | missing | The Vox Rooms goal. `luxd-pty`'s copy of the screen makes "what's on screen / is it waiting for input" possible without a Display. |
| 1.10 | The shell inherited the Display's environment, not the user's | P0 | fixed | Found live: with the spike's isolated `HOME`, `cd ~` landed in the Display's state directory and zsh skipped `~/.zshrc`, so there was no completion, history or direnv. Programs now get `HOME`, `USER`, `LOGNAME` and `SHELL` from the user database, without the Display-only variables. This also matters when Lux runs as a launchd service with a minimal environment. |
| 1.11 | The shell inherits secrets from its directory's `.envrc` | P1 | missing | direnv exports API keys and tokens into the terminal, same as in kitty. Not specific to Lux, but a terminal that agents can start (1.3) should account for it. |

## 2. Input

| # | Limitation | Pri | Status | Notes |
|---|---|---|---|---|
| 2.1 | Tab didn't reach the shell (no tab completion) | P0 | fixed | ImGui's built-in Tab focus-cycling took it; the terminal child now sets `no_nav_inputs`. |
| 2.2 | Input-method (IME) composition | P1 | partial | Committed text works; the in-progress text isn't shown at the cursor, and the IME isn't positioned at the cursor. |
| 2.3 | Option as Meta (Alt) on macOS | P1 | missing | Option currently composes characters (é, ∑). Needs a setting, like other macOS terminals. |
| 2.4 | Key repeat, dead keys, non-US layouts | P1 | partial | Repeat works; other layouts and dead keys aren't tested. |
| 2.5 | Function keys above F12, media keys, keypad | P2 | partial | F1–F12 are mapped; the numeric keypad is mapped only for Enter. |
| 2.6 | Copy and paste shortcuts aren't configurable | P2 | missing | Cmd+C/V on macOS, Ctrl+Shift+C/V elsewhere. Conflicts with Lux menus aren't designed. |
| 2.7 | No context menu (copy, paste, clear, select all) | P2 | missing | Right-click is sent to the program when it has mouse tracking on. |
| 2.8 | Mouse wheel scroll speed and smooth scrolling | P2 | partial | Fixed at 3 lines per notch; trackpad scrolling isn't smooth. |
| 2.9 | The Lux keyboard boundary isn't specified | P1 | partial | Lux binds no global keys today. A product needs a rule for which keys the Lux UI may take while a terminal has focus. |

## 3. Appearance

| # | Limitation | Pri | Status | Notes |
|---|---|---|---|---|
| 3.1 | No theme support | P1 | missing | Colours are fixed to imgui_terminal's defaults. They should follow Lux's 17 themes (dark and light), or offer terminal themes. Ghostty can take a full palette, foreground, background and cursor colour. |
| 3.2 | No font size control for the terminal | P1 | missing | The font is fixed at 14 px (times Lux's UI scale). Needs zoom (Cmd +/-/0) and a setting. ImGui 1.92 loads glyphs on demand at any size, so this is cheap. |
| 3.3 | Font choice is fixed (Inconsolata) | P2 | missing | Let users pick an installed monospace font. |
| 3.4 | Bold and italic are faked | P1 | partial | Bold is drawn twice, slightly offset; italic isn't drawn. Load the font's real bold, italic and bold-italic faces. |
| 3.5 | Emoji draw in black and white | P2 | partial | `LoadColor` didn't take effect with Apple Color Emoji (it's a bitmap font). Try Noto Color Emoji (CBDT/COLR) or a newer FreeType setup. |
| 3.6 | Wide characters aren't exactly two cells wide | P1 | partial | CJK is 2.14 cells, Hangul 1.57, emoji 1.79, so wide text can drift. Scale or centre each wide glyph into exactly 2 cells. |
| 3.7 | Fallback fonts are macOS-only paths | P1 | missing | Linux needs Noto CJK and Noto Color Emoji (or fontconfig lookup). |
| 3.8 | Box drawing and block characters come from the font | P2 | missing | Gaps can appear between lines. Polished terminals draw these themselves. |
| 3.9 | Ligatures | P2 | missing | Not supported (single-glyph runs). |
| 3.10 | Underline styles | P2 | partial | Only a straight underline; Ghostty reports curly, dotted, dashed and double, plus underline colour. |
| 3.11 | Cursor blink and styles | P2 | partial | Block, bar, underline and hollow are drawn; blinking isn't. |
| 3.12 | Strikethrough, overline, faint, hidden | P2 | partial | Hidden works; the others aren't drawn. |
| 3.13 | Hyperlinks (OSC 8) and clickable URLs | P2 | missing | Ghostty tracks hyperlinks; nothing opens them. |
| 3.14 | Inline images (kitty graphics, sixel) | P2 | missing | Ghostty decodes kitty graphics; nothing draws them. This is where Lux's rich-graphics advantage over herdr would show. |
| 3.15 | No padding or margin around the grid | P2 | missing | |
| 3.16 | Bell | P2 | missing | No visual or sound bell. |

## 4. Scrollback and selection

| # | Limitation | Pri | Status | Notes |
|---|---|---|---|---|
| 4.1 | No scrollbar | P1 | missing | Scrolling works with the wheel and Shift+PgUp/PgDn, but nothing shows where you are. |
| 4.2 | No search in scrollback | P1 | missing | Ghostty has a search API. |
| 4.3 | Scrollback size isn't configurable | P2 | missing | Fixed at 10,000 lines. |
| 4.4 | Selection: block selection, select all, and drag-select inside mouse-tracking apps | P2 | partial | Drag, double-click word, triple-click line, and Shift+drag work. |
| 4.5 | Copy as rich text or HTML | P2 | missing | Ghostty's formatter supports it. |

## 5. Rendering and performance

| # | Limitation | Pri | Status | Notes |
|---|---|---|---|---|
| 5.1 | Worst-case redraw is slow | P2 | partial | When every cell has its own colour, a full redraw takes about 37 ms (ADR-0003). Fix with cross-row style caching or a C helper. |
| 5.2 | Synchronized output (mode 2026) isn't honoured | P1 | missing | Programs that draw a frame at a time can show a half-drawn frame. Ghostty's render-hold callback fixes this. |
| 5.3 | Smooth scrolling and overscan | P2 | missing | Ghostty supports overscan for partial-row scrolling. |
| 5.4 | Flooding terminal next to a heavy Lux frame (1,000-row table) | P1 | partial | Measured: Lux stayed at 95-112 fps, and the table was the expensive part. It exposed 5.6. |
| 5.6 | Heavy output was throttled to about 0.1-0.5 MB/s | P1 | fixed (partly) | A macOS PTY buffers about 1 KB, and the pump read only what was ready at that instant. Two rounds of fixes reached 30-45 MB/s at about 8 ms per frame (STEP3.md). Native terminals reach hundreds of MB/s; `luxd-pty` reading out of process would remove the cap. |
| 5.5 | Frame budget under many terminals | P2 | fixed | One 6 ms read budget per frame, shared out; quiet terminals go first so busy ones inherit their share (STEP3.md). |

## 6. Platform and packaging

| # | Limitation | Pri | Status | Notes |
|---|---|---|---|---|
| 6.1 | pyghostty is 0.1.x, pinned exactly, using private API | P1 | partial | Contained in `ffi.py` (ADR-0002). Decide on upstreaming the missing API, forking, or another binding. |
| 6.2 | Linux not tested | P0 | missing | Fonts, PTY behaviour and keyboard are only tested on macOS. |
| 6.3 | Windows | P2 | missing | No pyghostty wheel; needs ConPTY. Lux treats Windows as a bonus (DES-001). |
| 6.4 | Accessibility | P2 | missing | ImGui exposes nothing to screen readers. |

## 7. Engineering

| # | Limitation | Pri | Status | Notes |
|---|---|---|---|---|
| 7.1 | Terminal-package test coverage | P0 | partial | Snapshot round-trips, native view cleanup, terminal wire codecs and renderer integration are now tested in `tests/`. Daemon lifecycle and live-window coverage remain. |
| 7.2 | Lux's OO and coupling ratchets | P0 | fixed | Quality pass before step 4 stage 2: new modules meet thresholds, touched modules improve without regressions, coupling and suppression gates pass. Scores and audit logs were generated by the normal update commands. |
| 7.3 | No DES entry, element-contract update or user docs | P0 | missing | ADRs 0001-0006 are spike records. |
| 7.4 | Lux's full test suite on macOS | P1 | in progress | The lux agent is fixing pre-existing macOS-only failures (display-spawn hang, socketpair reset, timing tests). |
| 7.5 | Session registry is a class-level singleton | P2 | partial | Fine for one Display per process. A product would inject it, and `luxd-pty` replaces it. |

## Found and fixed during the spike

- **Cursor about 10 px off, and columns not lining up** under Lux's 1.1 font
  scale (ADR-0005).
- **Tab not reaching the shell**, so no tab completion (2.1).
- **`exit` respawning the shell** (1.4).
- **The Display hanging on exit** with a live shell (1.6).
- **A busy terminal updating at idle speed** (ADR-0006).
- **Heavy output throttled to about 0.1 MB/s** by the PTY's 1 KB buffer:
  now 30-45 MB/s (5.6).
- **The shell got the Display's environment**: wrong `~`, no `.zshrc`, so no
  completion (1.10).
- **pyte-style "bigger box" look**: the terminal background didn't fill its pane.
