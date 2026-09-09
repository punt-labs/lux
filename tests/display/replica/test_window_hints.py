"""WindowHints — a frame's ImGui window-creation size, flags, and tab layout."""

from __future__ import annotations

from punt_lux.display.replica.window_hints import WindowHints


def test_defaults_are_none_size_none_flags_tab_layout() -> None:
    hints = WindowHints()
    assert hints.initial_size is None
    assert hints.flags is None
    assert hints.layout == "tab"


def test_constructor_arguments_are_read_back() -> None:
    hints = WindowHints(
        initial_size=(640, 480), flags={"no_resize": True}, layout="stack"
    )
    assert hints.initial_size == (640, 480)
    assert hints.flags == {"no_resize": True}
    assert hints.layout == "stack"


def test_flags_setter_replaces_the_stored_dict() -> None:
    hints = WindowHints()
    hints.flags = {"auto_resize": True}
    assert hints.flags == {"auto_resize": True}


def test_layout_setter_replaces_the_stored_mode() -> None:
    hints = WindowHints(layout="tab")
    hints.layout = "stack"
    assert hints.layout == "stack"
