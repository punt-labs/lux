# ADR-0004: Turn all input into bytes with Ghostty's own encoders

- **Status:** Accepted (spike)
- **Date:** 2026-11-15
- **Evidence:** `spikes/terminal/STEP2.md` (15/15 live checks);
  `src/punt_lux/display/terminal/input.py`, `keymap.py`, `selection.py`

## Context

What bytes a key, mouse event or paste should send depends on modes the
program sets while it runs:

- cursor-key mode (Up is `ESC [ A` or `ESC O A`) and keypad mode
- the kitty keyboard protocol
- mouse tracking mode and format (X10, SGR)
- bracketed paste

The pyte widget hand-codes escape sequences, so it gets these wrong or skips
them: no mouse reporting, no bracketed paste.

## Decision

The widget never builds escape sequences itself. It turns ImGui events into
Ghostty events, and Ghostty's encoders produce the bytes from the terminal's
current modes.

- **Keys** go through `ghostty_key_encoder_*`, mapped by physical key
  (`keymap.py`). When Shift produced the typed text, it is marked "consumed",
  so the encoder sends `A` rather than a CSI-u sequence.
- **macOS:** ImGui swaps Cmd and Ctrl. `terminal_mods()` swaps them back, so
  physical Ctrl is CTRL (Ctrl-C interrupts) and Cmd stays free for copy/paste.
- **Mouse** goes through `ghostty_mouse_encoder_*`, only when the program has
  enabled tracking. Shift+drag always selects locally.
- **Paste** goes through `ghostty_paste_encode`. It brackets the text when
  mode 2004 is on, and neutralises an embedded `ESC[201~`.
- **Selection** is Ghostty's: it follows scrolling, and Ghostty supplies the
  word and line rules and formats the copied text.
- **The one exception:** on the alternate screen with mode 1007, the wheel
  sends arrow keys (an xterm convention for `less` and `man`).

## Consequences

- **Verified live:**
  - Shell: typing, Ctrl-C, arrows (`cat -v` shows `^[[A`), paste, line wrap,
    resize.
  - vim: Shift keys, a mouse click moves the cursor, multi-line bracketed
    paste arrives intact.
  - top: `q` quits.
- Encoder spot checks:
  - Up is `\x1b[A`, and `\x1bOA` in application mode.
  - An SGR mouse click is `\x1b[<0;3;3M`.
  - Unbracketed paste turns newlines into CR and neutralises `ESC[201~`.
- New protocols arrive with Ghostty upgrades; nothing here needs to change.
- **Found live, and fixed:** ImGui's built-in Tab focus-cycling runs even
  with keyboard navigation off, so Tab never reached the shell (no tab
  completion). The terminal's child window now sets `no_nav_inputs`.
- **Open:** input-method composition (Chinese, Japanese) arrives only as
  committed text. The pre-edit (in-progress text) isn't shown.

## Alternatives considered

- **Hand-written escape tables (pyte widget):** wrong for application modes;
  no mouse, no bracketed paste.
- **A selection the widget tracks itself:** loses its place when output
  scrolls, and duplicates Ghostty.
