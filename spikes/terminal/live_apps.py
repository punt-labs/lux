"""Live full-screen apps through the real input path: vim (keys, mouse, bracketed paste) and top."""

from __future__ import annotations

import time
from pathlib import Path

from imgui_bundle import imgui

from live_test import Harness, check

K = imgui.Key


def click(h: Harness, col: int, row: int) -> None:
    cw = 7.0  # Inconsolata 15px advance (measured in check_glyphs)
    ch = imgui.get_text_line_height() if False else 15.0
    io = imgui.get_io()
    # child content origin: window pos (0,0) + window padding (8,8)
    io.add_mouse_pos_event(8 + col * cw + 2, 8 + row * ch + 4)
    h.frame()
    io.add_mouse_button_event(0, True)
    h.frame()
    io.add_mouse_button_event(0, False)
    h.frame()


def main() -> None:
    results = []
    f = Path("/tmp/spike_vim.txt")
    f.write_text("".join(f"line {i:03d} the quick brown fox\n" for i in range(1, 200)))
    h = Harness(["vim", "-u", "NONE", "-N", "-c", "set mouse=a", "-c", "syntax on", str(f)])
    h.run(0.8)
    h.focus()
    results.append(check("vim draws the file", "line 001 the quick brown fox" in h.screen()))
    results.append(
        check("vim enabled mouse tracking", bool(h.view.term.get("mouse_tracking", "bool")))
    )
    h.type("G")
    h.run(0.3)
    results.append(check("G jumps to end (shift+key)", "line 199" in h.screen()))
    h.type("gg")
    h.run(0.2)
    click(h, 10, 5)  # click row 5 -> cursor to line 006
    h.run(0.3)
    cur = h.view.rows.cursor
    results.append(check("mouse click moves vim's cursor", cur.viewport_y == 5,
                         f"cursor y={cur.viewport_y}"))  # fmt: skip
    h.type("o")
    h.view.input.paste("pasted one\npasted two")
    h.press(K.escape)
    h.run(0.3)
    scr = h.screen()
    results.append(check("bracketed paste into vim (no autoindent mangling)",
                         "pasted one\npasted two" in scr, scr[:400]))  # fmt: skip
    h.type(":q!")
    h.press(K.enter)
    h.run(0.5)
    results.append(check("vim quits", not h.t.alive))
    h.t.close()

    h = Harness(["top", "-s", "1"])
    t0 = time.monotonic()
    h.run(2.5)
    scr = h.screen()
    results.append(check("top renders its header and table", "PID" in scr and "COMMAND" in scr))
    h.focus()
    h.type("q")
    h.run(0.5)
    results.append(check("q quits top", not h.t.alive, f"after {time.monotonic() - t0:.1f}s"))
    h.t.close()
    print(f"\n{sum(results)}/{len(results)} passed")


if __name__ == "__main__":
    main()
