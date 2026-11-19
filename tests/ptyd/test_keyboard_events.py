"""Presses, repeats, releases and IME text cross the same encoder boundary."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from imgui_bundle import imgui

from punt_lux.display.terminal.input import Input
from punt_lux.display.terminal.input_events import KeyboardEvents, lib
from punt_lux.terminal.ffi import Terminal


@pytest.mark.parametrize(
    "pressed,repeat,released",
    [
        (True, False, False),
        (True, True, False),
        (False, False, True),
        (True, False, True),
        (False, False, False),
    ],
)
def test_poll_emits_all_key_actions_without_text_on_release(
    pressed: bool, repeat: bool, released: bool
) -> None:
    emit = Mock(return_value=True)
    test_repeat = repeat

    def is_pressed(_key: imgui.Key, *, repeat: bool) -> bool:
        return pressed and (repeat or not test_repeat)

    with (
        patch(
            "punt_lux.display.terminal.input_events.KEYMAP",
            {int(imgui.Key.a): lib.GHOSTTY_KEY_A},
        ),
        patch("punt_lux.display.terminal.input_events.terminal_mods", return_value=0),
        patch(
            "punt_lux.display.terminal.input_events.imgui.get_io",
            return_value=SimpleNamespace(
                input_queue_characters=[ord("a")] if pressed else []
            ),
        ),
        patch(
            "punt_lux.display.terminal.input_events.imgui.is_key_pressed",
            side_effect=is_pressed,
        ),
        patch(
            "punt_lux.display.terminal.input_events.imgui.is_key_released",
            return_value=released,
        ),
    ):
        assert KeyboardEvents.poll(emit) is (pressed or released)
    expected: list[tuple[int, int, str | None, int]] = []
    if pressed:
        expected.append(
            (
                lib.GHOSTTY_KEY_A,
                0,
                "a",
                lib.GHOSTTY_KEY_ACTION_REPEAT
                if repeat
                else lib.GHOSTTY_KEY_ACTION_PRESS,
            )
        )
    if released:
        expected.append((lib.GHOSTTY_KEY_A, 0, None, lib.GHOSTTY_KEY_ACTION_RELEASE))
    assert [call.args for call in emit.call_args_list] == expected


def test_empty_key_frame_forwards_ime_text_only_once() -> None:
    emit = Mock(return_value=True)
    with (
        patch("punt_lux.display.terminal.input_events.KEYMAP", {}),
        patch("punt_lux.display.terminal.input_events.terminal_mods", return_value=0),
        patch(
            "punt_lux.display.terminal.input_events.imgui.get_io",
            return_value=SimpleNamespace(input_queue_characters=[ord("é")]),
        ),
    ):
        assert KeyboardEvents.poll(emit)
    emit.assert_called_once_with(
        lib.GHOSTTY_KEY_UNIDENTIFIED, 0, "é", lib.GHOSTTY_KEY_ACTION_PRESS
    )


def test_kitty_event_reporting_receives_release_bytes() -> None:
    term = Terminal(20, 4)
    sent: list[bytes] = []
    encoder = Input(term, sent.append)
    try:
        term.feed(b"\x1b[>3u")
        assert encoder.key(lib.GHOSTTY_KEY_A, 0, "a", lib.GHOSTTY_KEY_ACTION_PRESS)
        sent.clear()
        assert encoder.key(lib.GHOSTTY_KEY_A, 0, None, lib.GHOSTTY_KEY_ACTION_RELEASE)
        assert sent == [b"\x1b[97;1:3u"]
    finally:
        encoder.close()
        term.close()


@pytest.mark.parametrize(
    "key_name,mods,expected",
    [
        ("GHOSTTY_KEY_A", 2, b"\x01"),
        ("GHOSTTY_KEY_E", 2, b"\x05"),
        ("GHOSTTY_KEY_K", 2, b"\x0b"),
        ("GHOSTTY_KEY_U", 2, b"\x15"),
        ("GHOSTTY_KEY_W", 2, b"\x17"),
        ("GHOSTTY_KEY_A", 0, b"a"),
    ],
)
def test_control_chord_without_text_encodes_c0_byte(
    key_name: str, mods: int, expected: bytes
) -> None:
    term = Terminal(20, 4)
    sent: list[bytes] = []
    encoder = Input(term, sent.append)
    text = "a" if expected == b"a" else None
    try:
        key = getattr(lib, key_name)
        assert encoder.key(key, mods, text, lib.GHOSTTY_KEY_ACTION_PRESS)
        assert sent == [expected]
    finally:
        encoder.close()
        term.close()


@pytest.mark.parametrize(
    "key_name,flags,expected",
    [
        ("GHOSTTY_KEY_A", b"\x1b[>1u", b"\x1b[97;5u"),
        ("GHOSTTY_KEY_E", b"\x1b[>1u", b"\x1b[101;5u"),
        ("GHOSTTY_KEY_K", b"\x1b[>3u", b"\x1b[107;5u"),
        ("GHOSTTY_KEY_DIGIT_1", b"\x1b[>1u", b"\x1b[49;5u"),
    ],
)
def test_control_chord_without_text_under_kitty_protocol(
    key_name: str, flags: bytes, expected: bytes
) -> None:
    term = Terminal(20, 4)
    sent: list[bytes] = []
    encoder = Input(term, sent.append)
    try:
        term.feed(flags)
        key = getattr(lib, key_name)
        assert encoder.key(key, 2, None, lib.GHOSTTY_KEY_ACTION_PRESS)
        assert sent == [expected]
    finally:
        encoder.close()
        term.close()
