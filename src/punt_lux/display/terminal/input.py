# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportAttributeAccessIssue=false
# pyright: reportMissingModuleSource=false, reportPrivateUsage=false
# (pyghostty is an untyped cffi binding: its ffi/lib members are unknown to pyright.)
"""ImGui keyboard, mouse and paste → bytes for the program (ADR-0004).

The widget never builds escape sequences itself. Ghostty's encoders decide
the bytes from the terminal's current modes: cursor-key and keypad modes, the
kitty keyboard protocol, mouse tracking mode and format (X10/SGR/…) and
bracketed paste. This module only translates ImGui events into Ghostty event
objects. The only exception is wheel-to-arrows, an xterm convention for
programs that use the alternate screen without the mouse (``less``, ``man``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from imgui_bundle import imgui

from punt_lux.display.terminal.ffi import Terminal, ffi, handle, init_sized, lib
from punt_lux.display.terminal.keymap import (
    CTRL,
    KEYMAP,
    NO_TEXT_KEYS,
    SHIFT,
    SUPER,
    terminal_mods,
)

__all__ = ["Input", "MouseFrame"]

WHEEL_LINES_MAX = 5  # wheel notches forwarded per frame, at most

_MOUSE_BUTTONS = (
    (imgui.MouseButton_.left, lib.GHOSTTY_MOUSE_BUTTON_LEFT),
    (imgui.MouseButton_.right, lib.GHOSTTY_MOUSE_BUTTON_RIGHT),
    (imgui.MouseButton_.middle, lib.GHOSTTY_MOUSE_BUTTON_MIDDLE),
)


@dataclass(frozen=True, slots=True)
class MouseFrame:
    """The pointer, relative to the grid origin, and the grid's geometry."""

    x: float
    y: float
    cell_w: float
    cell_h: float
    cols: int
    rows: int


class Input:
    """Owns one terminal's key and mouse encoders; sends bytes via ``write``."""

    def __init__(self, term: Terminal, write: Callable[[bytes], None]) -> None:
        self._term = term
        self._write = write
        self._key_encoder = ffi.new("GhosttyKeyEncoder*")
        lib.ghostty_key_encoder_new(ffi.NULL, self._key_encoder)
        self._mouse_encoder = ffi.new("GhosttyMouseEncoder*")
        lib.ghostty_mouse_encoder_new(ffi.NULL, self._mouse_encoder)
        self._out = ffi.new("char[]", 256)
        self._out_len = ffi.new("size_t*")
        self._buttons_down = 0  # bit per Ghostty button number
        self._last_cell: tuple[int, int] | None = None

    def close(self) -> None:
        lib.ghostty_key_encoder_free(self._key_encoder[0])
        lib.ghostty_mouse_encoder_free(self._mouse_encoder[0])

    # -- keyboard ----------------------------------------------------------
    def poll_keyboard(self) -> bool:
        """Send this frame's key presses and typed text. True if anything was sent."""
        mods = terminal_mods()
        io = imgui.get_io()
        chars = [chr(c) for c in io.input_queue_characters if c >= 0x20 and c != 0x7F]
        sent = False
        for imgui_key, ghostty_key in KEYMAP.items():
            key = imgui.Key(imgui_key)
            if not imgui.is_key_pressed(key, repeat=True):
                continue
            action = (
                lib.GHOSTTY_KEY_ACTION_PRESS
                if imgui.is_key_pressed(key, repeat=False)
                else lib.GHOSTTY_KEY_ACTION_REPEAT
            )
            # A printable key, without Ctrl/Cmd, carries this frame's typed text.
            text = None
            if imgui_key not in NO_TEXT_KEYS and chars and not mods & (CTRL | SUPER):
                text = chars.pop(0)
            sent |= self.key(ghostty_key, mods, text, action)
        # Text with no key event of its own: IME commits, Option-composed and
        # dead-key characters.
        for ch in chars:
            sent |= self.key(
                lib.GHOSTTY_KEY_UNIDENTIFIED,
                mods & ~SHIFT,
                ch,
                lib.GHOSTTY_KEY_ACTION_PRESS,
            )
        return sent

    def key(self, key: int, mods: int, text: str | None, action: int) -> bool:
        """Encode and send one key event. True if it produced bytes."""
        event = ffi.new("GhosttyKeyEvent*")
        lib.ghostty_key_event_new(ffi.NULL, event)
        try:
            ev = event[0]
            lib.ghostty_key_event_set_action(ev, action)
            lib.ghostty_key_event_set_key(ev, key)
            lib.ghostty_key_event_set_mods(ev, mods)
            # Shift that produced the text ('A', '!') is consumed, so the
            # encoder sends plain text rather than a CSI-u sequence.
            lib.ghostty_key_event_set_consumed_mods(ev, mods & SHIFT if text else 0)
            if text:
                data = text.encode()
                lib.ghostty_key_event_set_utf8(ev, data, len(data))
                if len(text) == 1:
                    lib.ghostty_key_event_set_unshifted_codepoint(ev, ord(text.lower()))
            encoder = self._key_encoder[0]
            lib.ghostty_key_encoder_setopt_from_terminal(encoder, handle(self._term))
            return self._emit(
                lib.ghostty_key_encoder_encode(
                    encoder, ev, self._out, len(self._out), self._out_len
                )
            )
        finally:
            lib.ghostty_key_event_free(event[0])

    # -- paste -------------------------------------------------------------
    def paste(self, text: str) -> None:
        """Send pasted text: bracketed when the program asked (mode 2004).

        Ghostty also neutralises control characters (an embedded
        ``ESC[201~`` cannot end the paste early) and maps newlines to CR
        when not bracketed.
        """
        if not text:
            return
        data = text.encode()
        src = ffi.new("char[]", data)  # rewritten in place by the encoder
        out = ffi.new("char[]", len(data) + 16)  # room for the two brackets
        n = ffi.new("size_t*")
        bracketed = self._term.mode(2004)
        if lib.ghostty_paste_encode(src, len(data), bracketed, out, len(out), n) == 0:
            self._write(ffi.buffer(out, n[0])[:])

    # -- mouse -------------------------------------------------------------
    def program_wants_mouse(self) -> bool:
        """Mouse tracking is on and Shift isn't held (Shift selects locally)."""
        tracking = bool(self._term.get("mouse_tracking", "bool"))
        return tracking and not imgui.get_io().key_shift

    def poll_mouse(self, frame: MouseFrame) -> None:
        """Forward this frame's buttons, motion and wheel to the program."""
        for imgui_button, button in _MOUSE_BUTTONS:
            if imgui.is_mouse_clicked(imgui_button):
                self._buttons_down |= 1 << button
                self._mouse(lib.GHOSTTY_MOUSE_ACTION_PRESS, button, frame)
            if imgui.is_mouse_released(imgui_button):
                self._buttons_down &= ~(1 << button)
                self._mouse(lib.GHOSTTY_MOUSE_ACTION_RELEASE, button, frame)
        cell = (int(frame.x // frame.cell_w), int(frame.y // frame.cell_h))
        if cell != self._last_cell:  # motion is reported per cell
            self._last_cell = cell
            held = next(
                (b for _, b in _MOUSE_BUTTONS if self._buttons_down & (1 << b)), 0
            )
            self._mouse(lib.GHOSTTY_MOUSE_ACTION_MOTION, held, frame)
        if wheel := imgui.get_io().mouse_wheel:
            button = (
                lib.GHOSTTY_MOUSE_BUTTON_FOUR
                if wheel > 0
                else lib.GHOSTTY_MOUSE_BUTTON_FIVE
            )
            for _ in range(min(WHEEL_LINES_MAX, max(1, int(abs(wheel))))):
                self._mouse(lib.GHOSTTY_MOUSE_ACTION_PRESS, button, frame)

    def _mouse(self, action: int, button: int, frame: MouseFrame) -> None:
        event = ffi.new("GhosttyMouseEvent*")
        lib.ghostty_mouse_event_new(ffi.NULL, event)
        try:
            ev = event[0]
            lib.ghostty_mouse_event_set_action(ev, action)
            if button:
                lib.ghostty_mouse_event_set_button(ev, button)
            lib.ghostty_mouse_event_set_mods(ev, terminal_mods())
            pos = ffi.new("GhosttyMousePosition*")
            pos.x, pos.y = frame.x, frame.y
            lib.ghostty_mouse_event_set_position(ev, pos[0])
            encoder = self._mouse_encoder[0]
            lib.ghostty_mouse_encoder_setopt_from_terminal(encoder, handle(self._term))
            size = init_sized("GhosttyMouseEncoderSize")
            size.screen_width = int(frame.cols * frame.cell_w)
            size.screen_height = int(frame.rows * frame.cell_h)
            size.cell_width, size.cell_height = int(frame.cell_w), int(frame.cell_h)
            lib.ghostty_mouse_encoder_setopt(
                encoder, lib.GHOSTTY_MOUSE_ENCODER_OPT_SIZE, size
            )
            pressed = ffi.new("bool*", self._buttons_down != 0)
            lib.ghostty_mouse_encoder_setopt(
                encoder, lib.GHOSTTY_MOUSE_ENCODER_OPT_ANY_BUTTON_PRESSED, pressed
            )
            self._emit(
                lib.ghostty_mouse_encoder_encode(
                    encoder, ev, self._out, len(self._out), self._out_len
                )
            )
        finally:
            lib.ghostty_mouse_event_free(event[0])

    def _emit(self, result: int) -> bool:
        """Send the encoder's output, if any. True if bytes were sent."""
        if result != 0 or not self._out_len[0]:
            return False
        self._write(ffi.buffer(self._out, self._out_len[0])[:])
        return True
