"""The unshifted codepoint Ghostty's key encoder needs for a key stroke."""

from __future__ import annotations

from typing import Final

from imgui_bundle import imgui

from punt_lux.display.terminal.keymap import KEYMAP

__all__ = ["UnshiftedCodepoint"]

_PHYSICAL: Final[dict[int, int]] = {
    KEYMAP[int(imgui.Key.a) + i]: ord("a") + i for i in range(26)
} | {KEYMAP[int(imgui.Key._0) + i]: ord("0") + i for i in range(10)}


class UnshiftedCodepoint:
    """Resolve a stroke's unshifted codepoint from its text, else its physical key.

    Ghostty derives Ctrl-A's C0 byte, and the kitty protocol's ``CSI 97;5u``,
    from this codepoint. A control chord arrives with its text suppressed (the
    byte must come from the encoder), so a letter or digit key supplies the
    codepoint itself.
    """

    @staticmethod
    def of(key: int, text: str) -> int:
        """Return the codepoint, or 0 (Ghostty's own "unset") when there is none."""
        if len(text) == 1:
            lower = text.lower()
            return ord(lower if len(lower) == 1 else text)
        return _PHYSICAL.get(key, 0)
