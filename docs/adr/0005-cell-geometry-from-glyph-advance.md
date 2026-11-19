# ADR-0005: Measure the cell from the glyph advance, not `calc_text_size`

- **Status:** Accepted (spike)
- **Date:** 2026-11-15
- **Evidence:** `spikes/terminal/STEP3.md` (found live by Jim);
  `src/punt_lux/display/terminal/painter.py` (`CellGrid`)

## Context

A terminal is a grid. Characters, the cursor, the selection, background colours
and mouse clicks must all agree on where column *n* is.

The widget first measured a cell with `imgui.calc_text_size("M").x`. That was
exact in the standalone demo, but not inside Lux:

- Lux scales all text by 1.1 (`font_scale_main`, a window setting). So
  Inconsolata 14 px is drawn at 15 px, and each character is **7.5 px** wide.
- `calc_text_size` rounds up to whole pixels and reported **8 px**.
- ImGui drew text at 7.5 px per column, but the cursor and the start of each
  coloured run were placed every 8 px. That is 0.5 px of error per column.

Jim saw both results: the cursor about 10 px to the right of where typing goes,
and `ls -F` columns not lining up, so the font looked proportional.

## Decision

- Measure the cell width from the font's real glyph advance at the current
  size: `get_font().get_font_baked(size).find_glyph('M').advance_x`.
- Compute one `CellGrid` (origin, cell width, cell height) per frame. Use it
  for painting, cursor, selection, mouse hit-testing and sizing the grid.
- Use a strictly monospace font (Inconsolata, shipped with imgui-bundle),
  separate from Lux's proportional UI font.

## Consequences

- Jim confirmed both problems gone.
- Reproduced at scale 1.1: the glyph advance is 7.5, while `calc_text_size`
  gives 8, 15, 23, 30… (rounded); the gap between the two is exactly the drift.
- Any font size or scale now lines up. That matters because font size is a user
  setting.
- Each run is still one `add_text` call. With the grid on ImGui's own advance,
  the glyphs already land on the grid.

## Alternatives considered

- **Force scale 1.0 inside the terminal:** fragile, and fights the user's
  setting.
- **Pick a font size whose advance is a whole number:** breaks again on the
  next size or font change.
- **Draw each character at its own cell:** always aligned, but many more draw
  calls. Unnecessary once the grid uses the real advance.
