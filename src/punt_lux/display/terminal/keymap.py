# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportAttributeAccessIssue=false
# pyright: reportMissingModuleSource=false, reportPrivateUsage=false
# (pyghostty is an untyped cffi binding: its ffi/lib members are unknown to pyright.)
"""ImGui keys and modifiers → Ghostty's key and modifier codes.

The mapping is by physical key; Ghostty's key encoder then turns
(key, modifiers, text) into exactly the bytes the program expects, honouring
cursor-key mode, the kitty keyboard protocol and so on (ADR-0004).
"""

from __future__ import annotations

from imgui_bundle import imgui

from punt_lux.display.terminal.ffi import lib

__all__ = [
    "ALT",
    "CTRL",
    "KEYMAP",
    "NO_TEXT_KEYS",
    "SHIFT",
    "SUPER",
    "terminal_mods",
]

# GHOSTTY_MODS_* are C macros, which cffi does not expose; these are their values.
SHIFT, CTRL, ALT, SUPER = 1, 2, 4, 8

_K = imgui.Key
_SPECIAL_KEYS: dict[int, str] = {
    _K.enter: "ENTER", _K.keypad_enter: "NUMPAD_ENTER", _K.escape: "ESCAPE",
    _K.backspace: "BACKSPACE", _K.tab: "TAB", _K.space: "SPACE",
    _K.left_arrow: "ARROW_LEFT", _K.right_arrow: "ARROW_RIGHT",
    _K.up_arrow: "ARROW_UP", _K.down_arrow: "ARROW_DOWN",
    _K.home: "HOME", _K.end: "END", _K.page_up: "PAGE_UP", _K.page_down: "PAGE_DOWN",
    _K.insert: "INSERT", _K.delete: "DELETE",
    _K.minus: "MINUS", _K.equal: "EQUAL", _K.comma: "COMMA", _K.period: "PERIOD",
    _K.slash: "SLASH", _K.semicolon: "SEMICOLON", _K.apostrophe: "QUOTE",
    _K.grave_accent: "BACKQUOTE", _K.backslash: "BACKSLASH",
    _K.left_bracket: "BRACKET_LEFT", _K.right_bracket: "BRACKET_RIGHT",
}  # fmt: skip
_NAMED: dict[int, str] = {
    **_SPECIAL_KEYS,
    **{int(_K.a) + i: chr(ord("A") + i) for i in range(26)},
    **{int(_K._0) + i: f"DIGIT_{i}" for i in range(10)},
    **{int(getattr(_K, f"f{i}")): f"F{i}" for i in range(1, 13)},
}

KEYMAP: dict[int, int] = {
    int(key): getattr(lib, f"GHOSTTY_KEY_{name}") for key, name in _NAMED.items()
}
"""ImGui key value → ``GHOSTTY_KEY_*``."""

NO_TEXT_KEYS = frozenset(
    int(k) for k in (_K.enter, _K.keypad_enter, _K.escape, _K.backspace, _K.tab)
)
"""Keys whose text event, if any, is not terminal input: the encoder owns them."""


class TerminalModifiers:
    """Translate physical keyboard modifiers into terminal protocol flags."""

    @staticmethod
    def terminal_mods() -> int:
        """The held modifiers as Ghostty ``MODS`` bits, by *physical* key.

        With ``io.config_mac_osx_behaviors`` (Lux's default on macOS) ImGui swaps
        Cmd and Ctrl: physical Ctrl arrives as ``key_super`` and Cmd as
        ``key_ctrl``. A terminal must see physical Ctrl as CTRL (Ctrl-C is
        SIGINT), so undo the swap here.
        """
        io = imgui.get_io()
        mac = io.config_mac_osx_behaviors
        ctrl, cmd = (io.key_super, io.key_ctrl) if mac else (io.key_ctrl, io.key_super)
        return (
            (SHIFT if io.key_shift else 0)
            | (CTRL if ctrl else 0)
            | (ALT if io.key_alt else 0)
            | (SUPER if cmd else 0)
        )


terminal_mods = TerminalModifiers.terminal_mods
