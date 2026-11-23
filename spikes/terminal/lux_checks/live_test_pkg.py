"""Scripted live test: a real shell in a PTY, driven through GhosttyTerminalView's input path.

Simulates ImGui key/char input (io.add_key_event / add_input_character) in a
headless ImGui context, so keystrokes go through exactly the code a user's
typing would (poll_keyboard -> Ghostty key encoder -> PTY), then checks the
screen text Ghostty reports. No window needed.
"""

from __future__ import annotations

import os
import time

from imgui_bundle import ImVec2, imgui

import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1])); import demo
from punt_lux.display.terminal.view import TerminalView as GhosttyTerminalView
from punt_lux.pty.holder import PtyHolder as PtyProcess

K = imgui.Key


class Harness:
    def __init__(self, argv: list[str]) -> None:
        imgui.create_context()
        io = imgui.get_io()
        io.display_size = ImVec2(1400, 800)
        io.delta_time = 1 / 60
        io.backend_flags |= imgui.BackendFlags_.renderer_has_textures.value
        io.config_mac_osx_behaviors = False  # Linux-style Ctrl for the test
        self.font = io.fonts.add_font_from_file_ttf(
            str(demo.ASSETS / "fonts/Inconsolata-Medium.ttf"), 15.0
        )
        self.view = GhosttyTerminalView(100, 30)
        self.t = PtyProcess(argv, cols=100, rows=30)
        self.view.on_input = self.t.write
        self.view.on_resize = self.t.resize
        self.frames = 0

    def frame(self) -> None:
        self.view.feed(self.t.pump())
        imgui.new_frame()
        imgui.push_font(self.font, 15.0)
        imgui.set_next_window_pos(ImVec2(0, 0))
        imgui.set_next_window_size(ImVec2(1400, 800))
        imgui.begin("t", None, imgui.WindowFlags_.no_decoration)
        self.view.render_in_child("term")
        imgui.end()
        imgui.pop_font()
        imgui.render()
        self.frames += 1

    def run(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.frame()
            time.sleep(1 / 120)

    def focus(self) -> None:  # click into the child so it has keyboard focus
        io = imgui.get_io()
        io.add_mouse_pos_event(300, 300)
        io.add_mouse_button_event(0, True)
        self.frame()
        io.add_mouse_button_event(0, False)
        self.frame()

    def type(self, text: str) -> None:
        io = imgui.get_io()
        for ch in text:
            key = _key_for(ch)
            if ch.isupper():
                io.add_key_event(K.left_shift, True)
                io.add_key_event(imgui.Key.mod_shift, True)
            if key is not None:
                io.add_key_event(key, True)
            io.add_input_character(ord(ch))
            self.frame()
            if key is not None:
                io.add_key_event(key, False)
            if ch.isupper():
                io.add_key_event(K.left_shift, False)
                io.add_key_event(imgui.Key.mod_shift, False)
            self.frame()

    def press(self, key: imgui.Key, ctrl: bool = False) -> None:
        io = imgui.get_io()
        if ctrl:
            io.add_key_event(K.left_ctrl, True)
            io.add_key_event(imgui.Key.mod_ctrl, True)
        io.add_key_event(key, True)
        self.frame()
        io.add_key_event(key, False)
        if ctrl:
            io.add_key_event(K.left_ctrl, False)
            io.add_key_event(imgui.Key.mod_ctrl, False)
        self.frame()

    def screen(self) -> str:
        return self.view.term.text()


def _key_for(ch: str) -> imgui.Key | None:
    if ch.isalpha() and ch.isascii():
        return imgui.Key(int(K.a) + ord(ch.lower()) - ord("a"))
    if ch.isdigit():
        return imgui.Key(int(K._0) + int(ch))
    return {" ": K.space, "-": K.minus, ".": K.period, "/": K.slash, "=": K.equal,
            "'": K.apostrophe, ";": K.semicolon, ",": K.comma}.get(ch)  # fmt: skip


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  -- ' + detail) if detail and not ok else ''}")
    return ok


def main() -> None:
    os.environ["PS1"] = "$ "
    results = []
    h = Harness(["/bin/bash", "--norc", "--noprofile", "-i"])
    h.run(0.5)
    h.focus()
    h.type("echo hello Ghostty")
    h.press(K.enter)
    h.run(0.4)
    results.append(
        check("typing + Enter reaches the shell", "hello Ghostty" in h.screen().split("echo")[-1])
    )
    h.type("echo $COLUMNS x $LINES")
    h.press(K.enter)
    h.run(0.4)
    cols, rows = h.view.cols, h.view.rows
    results.append(check("resize reaches the PTY", f"{cols} x {rows}" in h.screen(),
                         f"view {cols}x{rows}, screen tail: {h.screen()[-120:]!r}"))  # fmt: skip
    h.type("sleep 30")
    h.press(K.enter)
    h.run(0.3)
    h.press(K.c, ctrl=True)
    h.run(0.4)
    results.append(check("Ctrl-C interrupts", "^C" in h.screen()))
    h.type("cat -v")
    h.press(K.enter)
    h.run(0.3)
    h.press(K.up_arrow)
    h.press(K.left_arrow)
    h.run(0.3)
    results.append(check("arrow keys encoded (cat -v shows ^[[A^[[D)", "^[[A^[[D" in h.screen(),
                         h.screen()[-200:]))  # fmt: skip
    h.press(K.enter)  # EOF only counts at the start of a line in canonical mode
    h.press(K.d, ctrl=True)
    h.run(0.3)
    h.view.input.paste("echo pasted\n")
    h.run(0.4)
    results.append(
        check("paste reaches the shell", "pasted" in h.screen().split("echo pasted")[-1])
    )
    h.type("printf 'X%.0s' $(seq 250)")
    h.press(K.enter)
    h.run(0.4)
    results.append(check("long output wraps", "X" * h.view.cols in h.screen()))
    h.type("exit")
    h.press(K.enter)
    h.run(0.5)
    results.append(check("shell exit detected", not h.t.alive))
    h.t.close()
    print(f"\n{sum(results)}/{len(results)} passed, {h.frames} frames")


if __name__ == "__main__":
    main()
