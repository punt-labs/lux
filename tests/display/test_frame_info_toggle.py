"""FrameInfoToggle — what a click does to the popup, and what it says about it."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from punt_lux.display.menus.frame_info_button import FrameInfoButton
from punt_lux.domain.identity import HubId
from tests.menu_doubles import FakeImGui, Vec2, make_frame

if TYPE_CHECKING:
    import pytest

    from punt_lux.display.replica.frame import Frame

_HUB = HubId.stub()
_ROWS = (("Client", "lux"), ("Kind", "agent"))
_UNKNOWN = (("Owner", "unknown"),)
_GLYPH_CLICK = Vec2(470.0, 110.0)  # inside the glyph for menu_doubles' window
_OFF_GLYPH = Vec2(150.0, 250.0)  # inside that window, nowhere near the glyph


class _Facts:
    """A ``facts_for`` double whose answer can change after the popup opens."""

    rows: tuple[tuple[str, str], ...] | None

    def __init__(self, rows: tuple[tuple[str, str], ...] | None) -> None:
        self.rows = rows

    def __call__(
        self, _frame_id: str, _hub: HubId
    ) -> tuple[tuple[str, str], ...] | None:
        return self.rows


def _frame_for(_frame_id: str, _hub: HubId) -> Frame | None:
    return make_frame("f1", hub=_HUB)


def _click_glyph(button: FrameInfoButton) -> None:
    imgui = FakeImGui()
    imgui.click_at(_GLYPH_CLICK)
    button.render(make_frame("f1", hub=_HUB), imgui)


def _warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno == logging.WARNING]


def test_a_click_without_replicated_facts_warns_with_hub_and_frame(
    caplog: pytest.LogCaptureFixture,
) -> None:
    button = FrameInfoButton(_frame_for, _Facts(None))
    with caplog.at_level(logging.WARNING, logger="punt_lux.display.menus"):
        _click_glyph(button)

    assert f"hub={_HUB} frame=f1" in caplog.text
    assert button.popup.rows == _UNKNOWN


def test_a_click_with_replicated_facts_does_not_warn(
    caplog: pytest.LogCaptureFixture,
) -> None:
    button = FrameInfoButton(_frame_for, _Facts(_ROWS))
    with caplog.at_level(logging.WARNING, logger="punt_lux.display.menus"):
        _click_glyph(button)

    assert _warnings(caplog) == []


def test_facts_arriving_after_opening_replace_the_unknown_row() -> None:
    facts = _Facts(None)
    button = FrameInfoButton(_frame_for, facts)
    _click_glyph(button)

    facts.rows = _ROWS
    button.render_popup(FakeImGui())

    assert button.popup.rows == _ROWS


def test_rereading_facts_each_frame_stays_silent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The warning belongs to the click: the per-frame re-read must not log."""
    button = FrameInfoButton(_frame_for, _Facts(None))
    with caplog.at_level(logging.DEBUG, logger="punt_lux.display.menus"):
        _click_glyph(button)
        before = len(caplog.records)
        imgui = FakeImGui()
        for _ in range(5):
            button.render_popup(imgui)

    assert len(caplog.records) == before


def _frame(
    button: FrameInfoButton,
    imgui: FakeImGui,
    frame_id: str = "f1",
    *,
    draws_frame: bool = True,
) -> None:
    """Run one display frame: the frame's glyph (if drawn), then the popup pass."""
    if draws_frame:
        button.render(make_frame(frame_id, hub=_HUB), imgui)
    button.render_popup(imgui)


def _press(pos: Vec2) -> FakeImGui:
    imgui = FakeImGui()
    imgui.press_at(pos)
    return imgui


def _release(pos: Vec2) -> FakeImGui:
    imgui = FakeImGui()
    imgui.release_at(pos)
    return imgui


def _button() -> FrameInfoButton:
    return FrameInfoButton(_frame_for, _Facts(_ROWS))


def test_a_press_and_release_on_the_glyph_across_frames_opens_the_popup() -> None:
    button = _button()
    _frame(button, _press(_GLYPH_CLICK))
    _frame(button, _release(_GLYPH_CLICK))

    assert button.popup.is_open


def test_a_release_on_the_glyph_whose_press_began_off_it_does_nothing() -> None:
    button = _button()
    _frame(button, _press(_OFF_GLYPH))
    _frame(button, _release(_GLYPH_CLICK))

    assert not button.popup.is_open


def test_a_proper_click_opens_the_popup_after_an_ignored_release() -> None:
    button = _button()
    _frame(button, _press(_OFF_GLYPH))
    _frame(button, _release(_GLYPH_CLICK))
    _frame(button, _press(_GLYPH_CLICK))
    _frame(button, _release(_GLYPH_CLICK))

    assert button.popup.is_open


def test_a_press_on_one_frames_glyph_released_on_anothers_does_nothing() -> None:
    button = _button()
    _frame(button, _press(_GLYPH_CLICK), "f1")
    _frame(button, _release(_GLYPH_CLICK), "f2")

    assert not button.popup.is_open


def test_a_release_after_the_pressed_frame_vanished_leaves_no_press_behind() -> None:
    button = _button()
    _frame(button, _press(_GLYPH_CLICK))
    _frame(button, _release(_OFF_GLYPH), draws_frame=False)
    _frame(button, _release(_GLYPH_CLICK))

    assert not button.popup.is_open


def test_a_drag_released_off_the_glyph_leaves_no_press_behind() -> None:
    button = _button()
    _frame(button, _press(_GLYPH_CLICK))
    _frame(button, _release(_OFF_GLYPH))
    _frame(button, _release(_GLYPH_CLICK))

    assert not button.popup.is_open


def test_a_press_in_flight_survives_the_frames_it_is_held_across() -> None:
    button = _button()
    _frame(button, _press(_GLYPH_CLICK))
    _frame(button, FakeImGui())
    _frame(button, FakeImGui())
    _frame(button, _release(_GLYPH_CLICK))

    assert button.popup.is_open


def test_an_ignored_release_is_logged_once_at_debug_with_the_frame(
    caplog: pytest.LogCaptureFixture,
) -> None:
    button = _button()
    with caplog.at_level(logging.DEBUG, logger="punt_lux.display.menus"):
        _frame(button, _release(_GLYPH_CLICK))
        _frame(button, FakeImGui())

    ignored = [r for r in caplog.records if "ignored" in r.getMessage()]
    assert [(r.levelno, r.getMessage()) for r in ignored] == [
        (
            logging.DEBUG,
            f"glyph release for hub={_HUB} frame=f1 ignored: its press began elsewhere",
        )
    ]
