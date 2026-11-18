# pyright: reportMissingModuleSource=false
"""Clipboard shortcuts, separate from terminal drawing and sizing."""

from __future__ import annotations

from typing import Self

from imgui_bundle import imgui

from punt_lux.display.terminal.input import Input
from punt_lux.display.terminal.selection import Selection


class ClipboardActions:
    _input: Input
    _selection: Selection

    def __new__(cls, input_: Input, selection: Selection) -> Self:
        self = super().__new__(cls)
        self._input, self._selection = input_, selection
        return self

    def handle(self) -> bool:
        """Return true when copy or paste consumed the shortcut."""
        io = imgui.get_io()
        modifier = (
            io.key_ctrl
            if io.config_mac_osx_behaviors
            else (io.key_ctrl and io.key_shift)
        )
        if not modifier:
            return False
        if imgui.is_key_pressed(imgui.Key.c):
            if text := self._selection.text():
                imgui.set_clipboard_text(text)
            return True
        if imgui.is_key_pressed(imgui.Key.v):
            self._input.paste(imgui.get_clipboard_text() or "")
            return True
        return False
