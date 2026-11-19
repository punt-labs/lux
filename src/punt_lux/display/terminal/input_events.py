"""Translate ImGui key and captured pointer frames into Ghostty events."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Self

from imgui_bundle import imgui

from punt_lux.display.terminal.keymap import (
    CTRL,
    KEYMAP,
    NO_TEXT_KEYS,
    SHIFT,
    SUPER,
    terminal_mods,
)
from punt_lux.terminal.ffi import Terminal, ffi, handle, init_sized, lib as lib

if TYPE_CHECKING:
    from pyghostty._ffi import GhosttyKeyEncoderImpl, GhosttyMouseEncoderImpl, Pointer

    from punt_lux.display.terminal.input import MouseFrame

_MOUSE_BUTTONS = (
    (imgui.MouseButton_.left, lib.GHOSTTY_MOUSE_BUTTON_LEFT),
    (imgui.MouseButton_.right, lib.GHOSTTY_MOUSE_BUTTON_RIGHT),
    (imgui.MouseButton_.middle, lib.GHOSTTY_MOUSE_BUTTON_MIDDLE),
)


class KeyboardEvents:
    @staticmethod
    def modifiers() -> int:
        return terminal_mods()

    @staticmethod
    def consumed(mods: int, text: str | None) -> int:
        return mods & SHIFT if text else 0

    @staticmethod
    def _characters() -> list[str]:
        return [
            chr(c)
            for c in imgui.get_io().input_queue_characters
            if c >= 0x20 and c != 0x7F
        ]

    @staticmethod
    def poll(emit: Callable[[int, int, str | None, int], bool]) -> bool:
        mods = terminal_mods()
        chars = KeyboardEvents._characters()
        sent = False
        for imgui_key, ghostty_key in KEYMAP.items():
            key = imgui.Key(imgui_key)
            if imgui.is_key_pressed(key, repeat=True):
                action = (
                    lib.GHOSTTY_KEY_ACTION_PRESS
                    if imgui.is_key_pressed(key, repeat=False)
                    else lib.GHOSTTY_KEY_ACTION_REPEAT
                )
                text = None
                if (
                    imgui_key not in NO_TEXT_KEYS
                    and chars
                    and not mods & (CTRL | SUPER)
                ):
                    text = chars.pop(0)
                sent |= emit(ghostty_key, mods, text, action)
            if imgui.is_key_released(key):
                sent |= emit(ghostty_key, mods, None, lib.GHOSTTY_KEY_ACTION_RELEASE)
        for char in chars:
            sent |= emit(
                lib.GHOSTTY_KEY_UNIDENTIFIED,
                mods & ~SHIFT,
                char,
                lib.GHOSTTY_KEY_ACTION_PRESS,
            )
        return sent


class KeyEncoding:
    _text: dict[int, str]
    _encoder: Pointer[Pointer[GhosttyKeyEncoderImpl]]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._text = {}
        self._encoder = ffi.new("GhosttyKeyEncoder*")
        lib.ghostty_key_encoder_new(ffi.NULL, self._encoder)
        return self

    def close(self) -> None:
        self._text.clear()
        lib.ghostty_key_encoder_free(self._encoder[0])

    def encode(
        self,
        term: Terminal,
        stroke: tuple[int, int, str | None, int],
        out: Pointer[bytes],
        out_len: Pointer[int],
    ) -> int:
        key, mods, text, action = stroke
        if action == lib.GHOSTTY_KEY_ACTION_RELEASE:
            unshifted = self._text.pop(key, "")
            text = None
        else:
            unshifted = text or ""
            if text:
                self._text[key] = text
        event = ffi.new("GhosttyKeyEvent*")
        lib.ghostty_key_event_new(ffi.NULL, event)
        try:
            ev = event[0]
            lib.ghostty_key_event_set_action(ev, action)
            lib.ghostty_key_event_set_key(ev, key)
            lib.ghostty_key_event_set_mods(ev, mods)
            lib.ghostty_key_event_set_consumed_mods(
                ev, KeyboardEvents.consumed(mods, text)
            )
            if text:
                data = text.encode()
                lib.ghostty_key_event_set_utf8(ev, data, len(data))
            if len(unshifted) == 1:
                lower = unshifted.lower()
                lib.ghostty_key_event_set_unshifted_codepoint(
                    ev, ord(lower if len(lower) == 1 else unshifted)
                )
            lib.ghostty_key_encoder_setopt_from_terminal(self._encoder[0], handle(term))
            return lib.ghostty_key_encoder_encode(
                self._encoder[0], ev, out, len(out), out_len
            )
        finally:
            lib.ghostty_key_event_free(event[0])


class MouseEvents:
    _encoder: Pointer[Pointer[GhosttyMouseEncoderImpl]]
    _buttons_down: int
    _last_cell: tuple[int, int] | None

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._encoder = ffi.new("GhosttyMouseEncoder*")
        lib.ghostty_mouse_encoder_new(ffi.NULL, self._encoder)
        self._buttons_down = 0
        self._last_cell = None
        return self

    @property
    def captured(self) -> bool:
        return bool(self._buttons_down)

    def close(self) -> None:
        lib.ghostty_mouse_encoder_free(self._encoder[0])

    def poll(
        self,
        frame: MouseFrame,
        term: Terminal,
        out: Pointer[bytes],
        out_len: Pointer[int],
        emit: Callable[[int], bool],
    ) -> None:
        self._buttons(frame, term, out, out_len, emit)
        cell = (int(frame.x // frame.cell_w), int(frame.y // frame.cell_h))
        if cell != self._last_cell:
            self._last_cell = cell
            held = next(
                (b for _, b in _MOUSE_BUTTONS if self._buttons_down & (1 << b)), 0
            )
            emit(
                self._encode(
                    lib.GHOSTTY_MOUSE_ACTION_MOTION, held, frame, term, out, out_len
                )
            )
        if frame.hovered and (wheel := imgui.get_io().mouse_wheel):
            button = (
                lib.GHOSTTY_MOUSE_BUTTON_FOUR
                if wheel > 0
                else lib.GHOSTTY_MOUSE_BUTTON_FIVE
            )
            for _ in range(min(5, max(1, int(abs(wheel))))):
                emit(
                    self._encode(
                        lib.GHOSTTY_MOUSE_ACTION_PRESS,
                        button,
                        frame,
                        term,
                        out,
                        out_len,
                    )
                )

    def _buttons(
        self,
        frame: MouseFrame,
        term: Terminal,
        out: Pointer[bytes],
        out_len: Pointer[int],
        emit: Callable[[int], bool],
    ) -> None:
        for imgui_button, button in _MOUSE_BUTTONS:
            if frame.hovered and imgui.is_mouse_clicked(imgui_button):
                self._buttons_down |= 1 << button
                emit(
                    self._encode(
                        lib.GHOSTTY_MOUSE_ACTION_PRESS,
                        button,
                        frame,
                        term,
                        out,
                        out_len,
                    )
                )
            if self._buttons_down & (1 << button) and imgui.is_mouse_released(
                imgui_button
            ):
                self._buttons_down &= ~(1 << button)
                emit(
                    self._encode(
                        lib.GHOSTTY_MOUSE_ACTION_RELEASE,
                        button,
                        frame,
                        term,
                        out,
                        out_len,
                    )
                )

    def _encode(
        self,
        action: int,
        button: int,
        frame: MouseFrame,
        term: Terminal,
        out: Pointer[bytes],
        out_len: Pointer[int],
    ) -> int:
        event = ffi.new("GhosttyMouseEvent*")
        lib.ghostty_mouse_event_new(ffi.NULL, event)
        try:
            ev = event[0]
            lib.ghostty_mouse_event_set_action(ev, action)
            if button:
                lib.ghostty_mouse_event_set_button(ev, button)
            lib.ghostty_mouse_event_set_mods(ev, KeyboardEvents.modifiers())
            pos = ffi.new("GhosttyMousePosition*")
            pos.x, pos.y = frame.x, frame.y
            lib.ghostty_mouse_event_set_position(ev, pos[0])
            encoder = self._encoder[0]
            lib.ghostty_mouse_encoder_setopt_from_terminal(encoder, handle(term))
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
            return lib.ghostty_mouse_encoder_encode(encoder, ev, out, len(out), out_len)
        finally:
            lib.ghostty_mouse_event_free(event[0])
