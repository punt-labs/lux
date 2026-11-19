"""Translate an ImGui keyboard frame, including releases, into Ghostty events."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Self, cast

from imgui_bundle import imgui

from punt_lux.display.terminal.keymap import (
    CTRL,
    KEYMAP,
    NO_TEXT_KEYS,
    SHIFT,
    SUPER,
    terminal_mods,
)
from punt_lux.terminal.ffi import Terminal, ffi, handle, lib as ghostty_lib

lib = cast("Any", ghostty_lib)  # The generated CFFI key declarations lack stubs.


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
    # Native CFFI handles have no Python stub types.
    _encoder: Any

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
        out: Any,
        out_len: Any,
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
            ev = cast("Any", event[0])  # Native GhosttyKeyEvent has no Python stub.
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
            return cast(
                "int",
                lib.ghostty_key_encoder_encode(
                    self._encoder[0], ev, out, len(out), out_len
                ),
            )
        finally:
            lib.ghostty_key_event_free(event[0])
