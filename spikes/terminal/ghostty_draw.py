"""Draw cached GhosttyRows into an ImGui draw list (rendering only, no input)."""

from __future__ import annotations

from imgui_bundle import ImVec2, imgui

from ghostty_rows import RGB, GhosttyRows


def u32(c: RGB, a: int = 0xFF) -> int:
    return (a << 24) | (c[2] << 16) | (c[1] << 8) | c[0]


def draw_rows(rows: GhosttyRows, origin: ImVec2, cw: float, ch: float) -> int:
    """Replay every row's runs. Returns the number of draw-list calls made."""
    dl = imgui.get_window_draw_list()
    ncols = max((r.x + r.ncells for row in rows.rows for r in row.runs), default=0)
    ox, oy = origin.x, origin.y
    n_rows = len(rows.rows)
    dl.add_rect_filled(origin, ImVec2(ox + max(ncols, 1) * cw, oy + n_rows * ch), u32(rows.bg))
    calls = 1
    for y, row in enumerate(rows.rows):
        py = oy + y * ch
        for b in row.bgs:
            px = ox + b.x * cw
            dl.add_rect_filled(ImVec2(px, py), ImVec2(px + b.ncells * cw, py + ch), u32(b.color))
            calls += 1
        for r in row.runs:
            px = ox + r.x * cw
            dl.add_text(ImVec2(px, py), u32(r.fg), r.text)
            calls += 1
            if r.underline:
                ly = py + ch - 1.0
                dl.add_line(ImVec2(px, ly), ImVec2(px + r.ncells * cw, ly), u32(r.fg))
                calls += 1
    cur = rows.cursor
    if cur.visible and cur.viewport_has_value:
        px, py = ox + cur.viewport_x * cw, oy + cur.viewport_y * ch
        dl.add_rect_filled(ImVec2(px, py), ImVec2(px + cw, py + ch), u32(rows.fg, 0x88))
        calls += 1
    return calls
