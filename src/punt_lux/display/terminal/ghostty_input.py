"""ImGui keyboard/mouse/paste -> terminal bytes, via Ghostty's own encoders.

Ghostty decides the bytes (cursor-key mode, kitty keyboard protocol, mouse
tracking mode and format, bracketed paste). We only translate ImGui events.
"""

from __future__ import annotations

from collections.abc import Callable

from imgui_bundle import imgui
from pyghostty import Terminal, ffi, lib
from pyghostty.core import init_sized

# GHOSTTY_MODS_* are C macros (not exposed through cffi); same bits tilix2 uses.
SHIFT, CTRL, ALT, SUPER = 1, 2, 4, 8

K = imgui.Key
_NAMED: dict[int, str] = {
    K.enter: "ENTER", K.keypad_enter: "NUMPAD_ENTER", K.escape: "ESCAPE",
    K.backspace: "BACKSPACE", K.tab: "TAB", K.space: "SPACE",
    K.left_arrow: "ARROW_LEFT", K.right_arrow: "ARROW_RIGHT",
    K.up_arrow: "ARROW_UP", K.down_arrow: "ARROW_DOWN",
    K.home: "HOME", K.end: "END", K.page_up: "PAGE_UP", K.page_down: "PAGE_DOWN",
    K.insert: "INSERT", K.delete: "DELETE",
    K.minus: "MINUS", K.equal: "EQUAL", K.comma: "COMMA", K.period: "PERIOD",
    K.slash: "SLASH", K.semicolon: "SEMICOLON", K.apostrophe: "QUOTE",
    K.grave_accent: "BACKQUOTE", K.backslash: "BACKSLASH",
    K.left_bracket: "BRACKET_LEFT", K.right_bracket: "BRACKET_RIGHT",
}  # fmt: skip
for _i in range(26):
    _NAMED[int(K.a) + _i] = chr(ord("A") + _i)
for _i in range(10):
    _NAMED[int(K._0) + _i] = f"DIGIT_{_i}"
for _i in range(1, 13):
    _NAMED[int(getattr(K, f"f{_i}"))] = f"F{_i}"

KEYMAP: dict[int, int] = {
    int(k): getattr(lib, f"GHOSTTY_KEY_{v}") for k, v in _NAMED.items()
}
# keys whose ImGui text event (if any) is not the terminal input -- the encoder owns them
_NO_TEXT = {int(k) for k in (K.enter, K.keypad_enter, K.escape, K.backspace, K.tab)}


def current_mods() -> tuple[int, int]:
    """(ghostty mods for the terminal, ghostty mods for the clipboard shortcut test).

    On macOS ImGui swaps Cmd and Ctrl (io.config_mac_osx_behaviors): physical
    Ctrl arrives as key_super and Cmd as key_ctrl. The terminal must see the
    physical Ctrl as CTRL.
    """
    io = imgui.get_io()
    mac = io.config_mac_osx_behaviors
    ctrl = io.key_super if mac else io.key_ctrl
    cmd = io.key_ctrl if mac else io.key_super
    m = (
        (SHIFT if io.key_shift else 0)
        | (CTRL if ctrl else 0)
        | (ALT if io.key_alt else 0)
    )
    m |= SUPER if cmd else 0
    return m, m


class Input:
    """Owns the key/mouse encoders for one terminal and writes bytes via `write`."""

    def __init__(self, term: Terminal, write: Callable[[bytes], None]) -> None:
        self.term = term
        self.write = write
        self._kenc = ffi.new("GhosttyKeyEncoder*")
        lib.ghostty_key_encoder_new(ffi.NULL, self._kenc)
        self._menc = ffi.new("GhosttyMouseEncoder*")
        lib.ghostty_mouse_encoder_new(ffi.NULL, self._menc)
        self._out = ffi.new("char[]", 256)
        self._n = ffi.new("size_t*")
        self._mouse_down = 0
        self._last_cell: tuple[int, int] | None = None

    def close(self) -> None:
        lib.ghostty_key_encoder_free(self._kenc[0])
        lib.ghostty_mouse_encoder_free(self._menc[0])

    # -- keyboard ---------------------------------------------------------
    def key(self, gkey: int, mods: int, text: str | None, action: int) -> bool:
        ev = ffi.new("GhosttyKeyEvent*")
        lib.ghostty_key_event_new(ffi.NULL, ev)
        try:
            lib.ghostty_key_event_set_action(ev[0], action)
            lib.ghostty_key_event_set_key(ev[0], gkey)
            lib.ghostty_key_event_set_mods(ev[0], mods)
            # shift that produced the text ('A', '!') is consumed: plain text, not CSI-u
            lib.ghostty_key_event_set_consumed_mods(ev[0], mods & SHIFT if text else 0)
            if text:
                b = text.encode()
                lib.ghostty_key_event_set_utf8(ev[0], b, len(b))
                if len(text) == 1:
                    lib.ghostty_key_event_set_unshifted_codepoint(
                        ev[0], ord(text.lower())
                    )
            lib.ghostty_key_encoder_setopt_from_terminal(self._kenc[0], self.term._t[0])
            r = lib.ghostty_key_encoder_encode(
                self._kenc[0], ev[0], self._out, len(self._out), self._n
            )
            if r == 0 and self._n[0]:
                self.write(ffi.buffer(self._out, self._n[0])[:])
                return True
            return False
        finally:
            lib.ghostty_key_event_free(ev[0])

    def poll_keyboard(self) -> bool:
        """Translate this frame's ImGui keys + text. Returns True if anything was sent."""
        io = imgui.get_io()
        mods, _ = current_mods()
        sent = False
        chars = [chr(c) for c in io.input_queue_characters if c >= 0x20 and c != 0x7F]
        for ikey, gkey in KEYMAP.items():
            k = imgui.Key(ikey)
            if not imgui.is_key_pressed(k, repeat=True):
                continue
            first = imgui.is_key_pressed(k, repeat=False)
            action = (
                lib.GHOSTTY_KEY_ACTION_PRESS if first else lib.GHOSTTY_KEY_ACTION_REPEAT
            )
            text: str | None = None
            # a printable key with no Ctrl/Super carries this frame's text
            if ikey not in _NO_TEXT and chars and not mods & (CTRL | SUPER):
                text = chars.pop(0)
            sent |= self.key(gkey, mods, text, action)
        # text with no matching key event (IME commit, Option-composed chars, dead keys)
        for ch in chars:
            unid = lib.GHOSTTY_KEY_UNIDENTIFIED
            sent |= self.key(unid, mods & ~SHIFT, ch, lib.GHOSTTY_KEY_ACTION_PRESS)
        return sent

    # -- paste ------------------------------------------------------------
    def paste(self, text: str) -> None:
        if not text:
            return
        data = text.encode()
        src = ffi.new("char[]", data)  # paste_encode rewrites in place
        out = ffi.new("char[]", len(data) + 16)
        n = ffi.new("size_t*")
        if (
            lib.ghostty_paste_encode(
                src, len(data), self.term.mode(2004), out, len(out), n
            )
            == 0
        ):
            self.write(ffi.buffer(out, n[0])[:])

    # -- mouse ------------------------------------------------------------
    def app_wants_mouse(self) -> bool:
        """The program enabled mouse tracking, and Shift is not held (Shift = local select)."""
        return (
            bool(self.term.get("mouse_tracking", "bool"))
            and not imgui.get_io().key_shift
        )

    def mouse(
        self,
        action: int,
        button: int,
        x: float,
        y: float,
        cw: float,
        ch: float,
        cols: int,
        rows: int,
    ) -> None:
        """Encode a mouse event at pixel (x, y) relative to the grid origin."""
        ev = ffi.new("GhosttyMouseEvent*")
        lib.ghostty_mouse_event_new(ffi.NULL, ev)
        try:
            lib.ghostty_mouse_event_set_action(ev[0], action)
            if button:
                lib.ghostty_mouse_event_set_button(ev[0], button)
            lib.ghostty_mouse_event_set_mods(ev[0], current_mods()[0])
            pos = ffi.new("GhosttyMousePosition*")
            pos.x, pos.y = x, y
            lib.ghostty_mouse_event_set_position(ev[0], pos[0])
            enc = self._menc[0]
            lib.ghostty_mouse_encoder_setopt_from_terminal(enc, self.term._t[0])
            sz = init_sized("GhosttyMouseEncoderSize")
            sz.screen_width, sz.screen_height = int(cols * cw), int(rows * ch)
            sz.cell_width, sz.cell_height = int(cw), int(ch)
            lib.ghostty_mouse_encoder_setopt(
                enc, lib.GHOSTTY_MOUSE_ENCODER_OPT_SIZE, sz
            )
            pressed = ffi.new("bool*", self._mouse_down != 0)
            lib.ghostty_mouse_encoder_setopt(
                enc, lib.GHOSTTY_MOUSE_ENCODER_OPT_ANY_BUTTON_PRESSED, pressed
            )
            r = lib.ghostty_mouse_encoder_encode(
                enc, ev[0], self._out, len(self._out), self._n
            )
            if r == 0 and self._n[0]:
                self.write(ffi.buffer(self._out, self._n[0])[:])
        finally:
            lib.ghostty_mouse_event_free(ev[0])

    def poll_mouse(
        self, mx: float, my: float, cw: float, ch: float, cols: int, rows: int
    ) -> None:
        """Forward this frame's mouse buttons/motion/wheel to the program (tracking mode only)."""
        buttons = (
            (imgui.MouseButton_.left, lib.GHOSTTY_MOUSE_BUTTON_LEFT),
            (imgui.MouseButton_.right, lib.GHOSTTY_MOUSE_BUTTON_RIGHT),
            (imgui.MouseButton_.middle, lib.GHOSTTY_MOUSE_BUTTON_MIDDLE),
        )
        act = lib
        for ib, gb in buttons:
            if imgui.is_mouse_clicked(ib):
                self._mouse_down |= 1 << gb
                self.mouse(
                    act.GHOSTTY_MOUSE_ACTION_PRESS, gb, mx, my, cw, ch, cols, rows
                )
            if imgui.is_mouse_released(ib):
                self._mouse_down &= ~(1 << gb)
                self.mouse(
                    act.GHOSTTY_MOUSE_ACTION_RELEASE, gb, mx, my, cw, ch, cols, rows
                )
        cell = (int(mx // cw), int(my // ch))
        if cell != self._last_cell:
            self._last_cell = cell
            held = next((gb for _, gb in buttons if self._mouse_down & (1 << gb)), 0)
            self.mouse(
                act.GHOSTTY_MOUSE_ACTION_MOTION, held, mx, my, cw, ch, cols, rows
            )
        wheel = imgui.get_io().mouse_wheel
        if wheel:
            gb = (
                lib.GHOSTTY_MOUSE_BUTTON_FOUR
                if wheel > 0
                else lib.GHOSTTY_MOUSE_BUTTON_FIVE
            )
            for _ in range(min(5, max(1, int(abs(wheel))))):
                self.mouse(
                    act.GHOSTTY_MOUSE_ACTION_PRESS, gb, mx, my, cw, ch, cols, rows
                )
