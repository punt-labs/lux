"""FrameInfoPopup — the title-bar glyph's popup, opened by open_for().

Rendered in ImGui's always-on-top popup layer (``open_popup`` +
``begin_popup``), so it sits above the frame that spawned it: one popup at a
time, anchored at the glyph, dismissed by ImGui itself on an outside click.
Addressed by ``(frame_id, hub)``, never a bare id, since two Hubs can mint
the identical frame id.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from punt_lux.display.menus.frame_info_button import FrameInfoButton
from punt_lux.display.menus.frame_info_popup import FrameInfoPopup
from punt_lux.display.menus.open_popup import OpenFrame
from punt_lux.display.replica.frame_visibility import FrameVisibility
from punt_lux.domain.identity import HubId
from tests.menu_doubles import FakeImGui, Vec2, make_frame

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest

    from punt_lux.display.replica.frame import Frame

_ROWS = (("Client", "lux"), ("Kind", "agent"))
_HUB = HubId.stub()
_OTHER_HUB = HubId("okinos", 2)
_POPUP_ID = "frame_info_popup"  # the stable popup-stack id FrameInfoPopup uses


def _frame_for(*ids: str, hub: HubId = _HUB) -> Callable[[str, HubId], Frame | None]:
    """A ``frame_for`` double: the named ids exist under ``hub``, nowhere else."""
    frames = {
        fid: make_frame(fid, visibility=FrameVisibility.ON_SCREEN, hub=hub)
        for fid in ids
    }

    def resolve(frame_id: str, resolved_hub: HubId) -> Frame | None:
        return frames.get(frame_id) if resolved_hub == hub else None

    return resolve


# A screen point inside the title-bar glyph's hit rect, given menu_doubles'
# fixed window origin (100, 100), size (400, 300), and 20px frame height.
_GLYPH_CLICK = Vec2(470.0, 110.0)


def _facts_for(
    *ids: str, hub: HubId = _HUB
) -> Callable[[str, HubId], tuple[tuple[str, str], ...] | None]:
    """A ``facts_for`` double: the named ids resolve to ``_ROWS`` under ``hub``."""

    def resolve(
        frame_id: str, resolved_hub: HubId
    ) -> tuple[tuple[str, str], ...] | None:
        return _ROWS if frame_id in ids and resolved_hub == hub else None

    return resolve


class TestOpening:
    def test_a_fresh_popup_is_closed(self) -> None:
        assert not FrameInfoPopup(_frame_for()).is_open

    def test_open_for_opens_the_popup(self) -> None:
        popup = FrameInfoPopup(_frame_for("f1"))
        popup.open_for(OpenFrame("f1", _HUB), _ROWS, (10.0, 20.0))
        assert popup.is_open

    def test_a_closed_popup_renders_nothing(self) -> None:
        popup = FrameInfoPopup(_frame_for("f1"))
        imgui = FakeImGui()
        popup.render(imgui)
        assert imgui.popups == ()

    def test_an_open_popup_renders_in_the_popup_layer(self) -> None:
        popup = FrameInfoPopup(_frame_for("f1"))
        popup.open_for(OpenFrame("f1", _HUB), _ROWS, (10.0, 20.0))
        imgui = FakeImGui()
        popup.render(imgui)
        assert imgui.popups == (_POPUP_ID,)

    def test_an_open_popup_renders_its_rows_verbatim(self) -> None:
        popup = FrameInfoPopup(_frame_for("f1"))
        popup.open_for(OpenFrame("f1", _HUB), _ROWS, (10.0, 20.0))
        imgui = FakeImGui()
        popup.render(imgui)
        assert imgui.table_rows == _ROWS

    def test_opening_opens_the_popup_stack_exactly_once(self) -> None:
        popup = FrameInfoPopup(_frame_for("f1"))
        popup.open_for(OpenFrame("f1", _HUB), _ROWS, (10.0, 20.0))
        imgui = FakeImGui()
        popup.render(imgui)
        assert imgui.opened_popup_ids == (_POPUP_ID,)
        popup.render(imgui)  # the second frame must not re-open the popup stack
        assert imgui.opened_popup_ids == (_POPUP_ID,)


class TestOneAtATime:
    def test_opening_a_second_frame_replaces_the_first(self) -> None:
        popup = FrameInfoPopup(_frame_for("f1", "f2"))
        popup.open_for(OpenFrame("f1", _HUB), _ROWS, (10.0, 20.0))

        popup.open_for(OpenFrame("f2", _HUB), (("Client", "quarry"),), (30.0, 40.0))

        imgui = FakeImGui()
        popup.render(imgui)
        assert imgui.table_rows == (("Client", "quarry"),)

    def test_only_one_popup_is_ever_open(self) -> None:
        popup = FrameInfoPopup(_frame_for("f1", "f2"))
        popup.open_for(OpenFrame("f1", _HUB), _ROWS, (10.0, 20.0))
        popup.open_for(OpenFrame("f2", _HUB), _ROWS, (30.0, 40.0))
        imgui = FakeImGui()
        popup.render(imgui)
        assert imgui.popups == (_POPUP_ID,)


class TestDismissal:
    def test_an_outside_click_shuts_the_popup(self) -> None:
        popup = FrameInfoPopup(_frame_for("f1"))
        popup.open_for(OpenFrame("f1", _HUB), _ROWS, (10.0, 20.0))
        imgui = FakeImGui()
        popup.render(imgui)  # opens and draws it in the popup layer
        imgui.dismiss_popup(_POPUP_ID)  # ImGui's own outside-click dismissal
        popup.render(imgui)  # begin_popup now reports it shut
        assert not popup.is_open

    def test_a_dismissal_by_imgui_is_logged_with_the_frame(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        popup = FrameInfoPopup(_frame_for("f1"))
        popup.open_for(OpenFrame("f1", _HUB), _ROWS, (10.0, 20.0))
        imgui = FakeImGui()
        popup.render(imgui)
        imgui.dismiss_popup(_POPUP_ID)
        with caplog.at_level(logging.INFO, logger="punt_lux.display.menus"):
            popup.render(imgui)
        assert f"hub={_HUB} frame=f1 closed: dismissed by imgui" in caplog.text

    def test_a_dismissed_popup_draws_nothing_further(self) -> None:
        popup = FrameInfoPopup(_frame_for("f1"))
        popup.open_for(OpenFrame("f1", _HUB), _ROWS, (10.0, 20.0))
        imgui = FakeImGui()
        popup.render(imgui)
        imgui.dismiss_popup(_POPUP_ID)
        popup.render(imgui)
        assert imgui.popups == (_POPUP_ID,)  # drawn on the first frame only


class TestAutoClose:
    def test_the_popup_closes_when_its_frame_is_gone(self) -> None:
        popup = FrameInfoPopup(_frame_for())  # the frame has since closed
        popup.open_for(OpenFrame("f1", _HUB), _ROWS, (10.0, 20.0))
        imgui = FakeImGui()
        popup.render(imgui)
        assert not popup.is_open
        assert imgui.popups == ()

    def test_a_vanished_frame_is_logged_once_with_hub_and_frame(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        popup = FrameInfoPopup(_frame_for())
        popup.open_for(OpenFrame("f1", _HUB), _ROWS, (10.0, 20.0))
        imgui = FakeImGui()
        with caplog.at_level(logging.INFO, logger="punt_lux.display.menus"):
            popup.render(imgui)
            popup.render(imgui)  # already closed: nothing further to say
        closes = [r for r in caplog.records if "closed:" in r.getMessage()]
        assert [r.getMessage() for r in closes] == [
            f"frame-info popup for hub={_HUB} frame=f1 closed: its frame is gone"
        ]

    def test_the_popup_stays_open_while_its_frame_still_exists(self) -> None:
        popup = FrameInfoPopup(_frame_for("f1"))
        popup.open_for(OpenFrame("f1", _HUB), _ROWS, (10.0, 20.0))
        imgui = FakeImGui()
        popup.render(imgui)
        assert popup.is_open


class TestReplaceRows:
    def test_replacing_rows_changes_what_the_open_popup_renders(self) -> None:
        popup = FrameInfoPopup(_frame_for("f1"))
        popup.open_for(OpenFrame("f1", _HUB), (("Owner", "unknown"),), (10.0, 20.0))
        popup.replace_rows(_ROWS)
        imgui = FakeImGui()
        popup.render(imgui)
        assert imgui.table_rows == _ROWS

    def test_the_open_frame_is_addressed_by_hub_and_id(self) -> None:
        popup = FrameInfoPopup(_frame_for("f1", hub=_OTHER_HUB))
        popup.open_for(OpenFrame("f1", _OTHER_HUB), _ROWS, (10.0, 20.0))
        assert popup.open_frame == OpenFrame("f1", _OTHER_HUB)

    def test_a_closed_popup_has_no_open_frame(self) -> None:
        assert FrameInfoPopup(_frame_for("f1")).open_frame is None


class TestHubScoping:
    """Two Hubs minting the identical frame id must never share one popup slot."""

    def test_a_frame_that_exists_only_under_another_hub_is_treated_as_gone(
        self,
    ) -> None:
        # "main" exists under _OTHER_HUB, not the Hub the popup was opened for.
        popup = FrameInfoPopup(_frame_for("main", hub=_OTHER_HUB))
        popup.open_for(OpenFrame("main", _HUB), _ROWS, (10.0, 20.0))
        imgui = FakeImGui()
        popup.render(imgui)
        assert not popup.is_open
        assert imgui.popups == ()

    def test_a_frame_that_exists_under_its_own_hub_stays_open(self) -> None:
        popup = FrameInfoPopup(_frame_for("main", hub=_HUB))
        popup.open_for(OpenFrame("main", _HUB), _ROWS, (10.0, 20.0))
        imgui = FakeImGui()
        popup.render(imgui)
        assert popup.is_open


class TestCloseButton:
    def test_the_close_button_shuts_the_popup(self) -> None:
        popup = FrameInfoPopup(_frame_for("f1"))
        popup.open_for(OpenFrame("f1", _HUB), _ROWS, (10.0, 20.0))
        imgui = FakeImGui(clicks={"##close"})
        popup.render(imgui)  # header close button clicked -> close_current_popup
        popup.render(imgui)  # begin_popup now reports the popup shut
        assert not popup.is_open

    def test_the_close_button_draws_nothing_after_dismissal(self) -> None:
        popup = FrameInfoPopup(_frame_for("f1"))
        popup.open_for(OpenFrame("f1", _HUB), _ROWS, (10.0, 20.0))
        imgui = FakeImGui(clicks={"##close"})
        popup.render(imgui)  # the close button arms the pending dismissal
        popup.render(imgui)  # the pending dismissal routes through close_current_popup
        drawn = len(imgui.popups)
        popup.render(imgui)  # dismissed: begin_popup now reports it shut
        assert len(imgui.popups) == drawn  # the third frame drew nothing more
        assert not popup.is_open

    def test_the_close_button_is_logged_once_with_the_frame(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        popup = FrameInfoPopup(_frame_for("f1"))
        popup.open_for(OpenFrame("f1", _HUB), _ROWS, (10.0, 20.0))
        imgui = FakeImGui(clicks={"##close"})
        with caplog.at_level(logging.INFO, logger="punt_lux.display.menus"):
            for _ in range(3):
                popup.render(imgui)
        closes = [r.getMessage() for r in caplog.records if "closed:" in r.getMessage()]
        assert closes == [
            f"frame-info popup for hub={_HUB} frame=f1 closed: dismissed by the user"
        ]

    def test_a_second_glyph_click_is_logged_once_with_the_frame(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        popup = FrameInfoPopup(_frame_for("f1"))
        popup.open_for(OpenFrame("f1", _HUB), _ROWS, (10.0, 20.0))
        imgui = FakeImGui()
        popup.render(imgui)
        popup.request_close()
        with caplog.at_level(logging.INFO, logger="punt_lux.display.menus"):
            popup.render(imgui)
            popup.render(imgui)
        closes = [r.getMessage() for r in caplog.records if "closed:" in r.getMessage()]
        assert closes == [
            f"frame-info popup for hub={_HUB} frame=f1 closed: dismissed by the user"
        ]

    def test_without_a_close_click_the_popup_stays_open(self) -> None:
        popup = FrameInfoPopup(_frame_for("f1"))
        popup.open_for(OpenFrame("f1", _HUB), _ROWS, (10.0, 20.0))
        imgui = FakeImGui()  # nothing clicked
        popup.render(imgui)
        popup.render(imgui)
        assert popup.is_open


class TestGlyphToggle:
    def test_clicking_the_glyph_opens_the_popup(self) -> None:
        button = FrameInfoButton(_frame_for("f1"), _facts_for("f1"))
        imgui = FakeImGui()
        imgui.click_at(_GLYPH_CLICK)
        button.render(make_frame("f1", hub=_HUB), imgui)
        assert button.popup.is_open_for(OpenFrame("f1", _HUB))

    def test_clicking_the_glyph_again_dismisses_the_open_popup(self) -> None:
        button = FrameInfoButton(_frame_for("f1"), _facts_for("f1"))
        frame = make_frame("f1", hub=_HUB)
        popup = button.popup
        popup.open_for(OpenFrame("f1", _HUB), _ROWS, (10.0, 20.0))
        imgui = FakeImGui()
        popup.render(imgui)  # the popup is open and drawn
        imgui.click_at(_GLYPH_CLICK)
        button.render(frame, imgui)  # a second glyph click requests dismissal
        popup.render(imgui)  # the pending close routes through close_current_popup
        assert not popup.is_open

    def test_the_glyph_reopens_the_popup_after_a_toggle_close(self) -> None:
        button = FrameInfoButton(_frame_for("f1"), _facts_for("f1"))
        frame = make_frame("f1", hub=_HUB)
        popup = button.popup
        popup.open_for(OpenFrame("f1", _HUB), _ROWS, (10.0, 20.0))
        toggle = FakeImGui()
        popup.render(toggle)
        toggle.click_at(_GLYPH_CLICK)
        button.render(frame, toggle)
        popup.render(toggle)
        assert not popup.is_open

        reopen = FakeImGui()
        reopen.click_at(_GLYPH_CLICK)
        button.render(frame, reopen)
        assert button.popup.is_open_for(OpenFrame("f1", _HUB))
