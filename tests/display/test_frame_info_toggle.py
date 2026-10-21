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
