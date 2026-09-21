"""FrameInfoPopup — the title-bar glyph's popup, opened by open_for().

Rendered in ImGui's always-on-top popup layer (``open_popup`` +
``begin_popup``), so it sits above the frame that spawned it: one popup at a
time, anchored at the glyph, dismissed by ImGui itself on an outside click.
Addressed by ``(frame_id, hub)``, never a bare id, since two Hubs can mint
the identical frame id (DES-c7xi round 3).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from punt_lux.display.menus.frame_info_popup import FrameInfoPopup
from punt_lux.display.replica.frame_visibility import FrameVisibility
from punt_lux.domain.identity import HubId
from tests.menu_doubles import FakeImGui, make_frame

if TYPE_CHECKING:
    from collections.abc import Callable

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


class TestOpening:
    def test_a_fresh_popup_is_closed(self) -> None:
        assert not FrameInfoPopup(_frame_for()).is_open

    def test_open_for_opens_the_popup(self) -> None:
        popup = FrameInfoPopup(_frame_for("f1"))
        popup.open_for("f1", _HUB, _ROWS, (10.0, 20.0))
        assert popup.is_open

    def test_a_closed_popup_renders_nothing(self) -> None:
        popup = FrameInfoPopup(_frame_for("f1"))
        imgui = FakeImGui()
        popup.render(imgui)
        assert imgui.popups == ()

    def test_an_open_popup_renders_in_the_popup_layer(self) -> None:
        popup = FrameInfoPopup(_frame_for("f1"))
        popup.open_for("f1", _HUB, _ROWS, (10.0, 20.0))
        imgui = FakeImGui()
        popup.render(imgui)
        assert imgui.popups == (_POPUP_ID,)

    def test_an_open_popup_renders_its_rows_verbatim(self) -> None:
        popup = FrameInfoPopup(_frame_for("f1"))
        popup.open_for("f1", _HUB, _ROWS, (10.0, 20.0))
        imgui = FakeImGui()
        popup.render(imgui)
        assert imgui.table_rows == _ROWS

    def test_opening_opens_the_popup_stack_exactly_once(self) -> None:
        popup = FrameInfoPopup(_frame_for("f1"))
        popup.open_for("f1", _HUB, _ROWS, (10.0, 20.0))
        imgui = FakeImGui()
        popup.render(imgui)
        assert imgui.opened_popup_ids == (_POPUP_ID,)
        popup.render(imgui)  # the second frame must not re-open the popup stack
        assert imgui.opened_popup_ids == (_POPUP_ID,)


class TestOneAtATime:
    def test_opening_a_second_frame_replaces_the_first(self) -> None:
        popup = FrameInfoPopup(_frame_for("f1", "f2"))
        popup.open_for("f1", _HUB, _ROWS, (10.0, 20.0))

        popup.open_for("f2", _HUB, (("Client", "quarry"),), (30.0, 40.0))

        imgui = FakeImGui()
        popup.render(imgui)
        assert imgui.table_rows == (("Client", "quarry"),)

    def test_only_one_popup_is_ever_open(self) -> None:
        popup = FrameInfoPopup(_frame_for("f1", "f2"))
        popup.open_for("f1", _HUB, _ROWS, (10.0, 20.0))
        popup.open_for("f2", _HUB, _ROWS, (30.0, 40.0))
        imgui = FakeImGui()
        popup.render(imgui)
        assert imgui.popups == (_POPUP_ID,)


class TestDismissal:
    def test_an_outside_click_shuts_the_popup(self) -> None:
        popup = FrameInfoPopup(_frame_for("f1"))
        popup.open_for("f1", _HUB, _ROWS, (10.0, 20.0))
        imgui = FakeImGui()
        popup.render(imgui)  # opens and draws it in the popup layer
        imgui.dismiss_popup(_POPUP_ID)  # ImGui's own outside-click dismissal
        popup.render(imgui)  # begin_popup now reports it shut
        assert not popup.is_open

    def test_a_dismissed_popup_draws_nothing_further(self) -> None:
        popup = FrameInfoPopup(_frame_for("f1"))
        popup.open_for("f1", _HUB, _ROWS, (10.0, 20.0))
        imgui = FakeImGui()
        popup.render(imgui)
        imgui.dismiss_popup(_POPUP_ID)
        popup.render(imgui)
        assert imgui.popups == (_POPUP_ID,)  # drawn on the first frame only


class TestAutoClose:
    def test_the_popup_closes_when_its_frame_is_gone(self) -> None:
        popup = FrameInfoPopup(_frame_for())  # the frame has since closed
        popup.open_for("f1", _HUB, _ROWS, (10.0, 20.0))
        imgui = FakeImGui()
        popup.render(imgui)
        assert not popup.is_open
        assert imgui.popups == ()

    def test_the_popup_stays_open_while_its_frame_still_exists(self) -> None:
        popup = FrameInfoPopup(_frame_for("f1"))
        popup.open_for("f1", _HUB, _ROWS, (10.0, 20.0))
        imgui = FakeImGui()
        popup.render(imgui)
        assert popup.is_open


class TestHubScoping:
    """Two Hubs minting the identical frame id must never share one popup slot."""

    def test_a_frame_that_exists_only_under_another_hub_is_treated_as_gone(
        self,
    ) -> None:
        # "main" exists under _OTHER_HUB, not the Hub the popup was opened for.
        popup = FrameInfoPopup(_frame_for("main", hub=_OTHER_HUB))
        popup.open_for("main", _HUB, _ROWS, (10.0, 20.0))
        imgui = FakeImGui()
        popup.render(imgui)
        assert not popup.is_open
        assert imgui.popups == ()

    def test_a_frame_that_exists_under_its_own_hub_stays_open(self) -> None:
        popup = FrameInfoPopup(_frame_for("main", hub=_HUB))
        popup.open_for("main", _HUB, _ROWS, (10.0, 20.0))
        imgui = FakeImGui()
        popup.render(imgui)
        assert popup.is_open
