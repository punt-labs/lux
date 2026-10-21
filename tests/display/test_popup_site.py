"""PopupSite — the info popup's state: open frame, rows, anchor, close request."""

from __future__ import annotations

from punt_lux.display.menus.popup_site import OpenFrame, PopupSite
from punt_lux.domain.identity import HubId
from tests.menu_doubles import FakeImGui

_HUB = HubId.stub()
_ROWS = (("Client", "lux"),)


def _open_site() -> PopupSite:
    site = PopupSite()
    site.open(OpenFrame("f1", _HUB), _ROWS, (10.0, 20.0))
    return site


def test_a_new_site_is_closed() -> None:
    assert PopupSite().frame is None


def test_opening_records_the_frame_rows_and_anchor() -> None:
    site = _open_site()
    assert (site.frame, site.rows, site.pos) == (
        OpenFrame("f1", _HUB),
        _ROWS,
        (10.0, 20.0),
    )


def test_closing_forgets_the_frame() -> None:
    site = _open_site()
    site.close()
    assert site.frame is None


def test_a_close_request_survives_until_the_site_closes() -> None:
    site = _open_site()
    site.request_close()
    assert site.is_close_requested


def test_closing_clears_a_pending_close_request() -> None:
    site = _open_site()
    site.request_close()
    site.close()
    assert not site.is_close_requested


def test_reopening_clears_a_pending_close_request() -> None:
    site = _open_site()
    site.request_close()
    site.open(OpenFrame("f2", _HUB), _ROWS, (0.0, 0.0))
    assert not site.is_close_requested


def test_placing_opens_the_popup_stack_once_per_opening() -> None:
    site = _open_site()
    imgui = FakeImGui()
    site.place(imgui, "p")
    site.place(imgui, "p")
    assert imgui.opened_popup_ids == ("p",)


def test_replacing_rows_keeps_the_open_frame() -> None:
    site = _open_site()
    site.replace_rows((("Client", "quarry"),))
    assert site.frame == OpenFrame("f1", _HUB)


def test_an_open_frame_names_its_hub_and_id() -> None:
    assert str(OpenFrame("f1", _HUB)) == f"hub={_HUB} frame=f1"
