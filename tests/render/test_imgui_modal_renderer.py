"""ImGuiModalRenderer opens the popup and routes an external close to the Hub.

The adapter under test is real, driven through a real ``ImGuiRendererFactory``
(for its ``WidgetState``); only the ImGui backend is faked at the render
boundary. Where the legacy ``ModalRenderer`` emits the ``closed`` invocation
itself, the ABC adapter fires ``ModalClosed`` through the element's handler
registry — so a capturing handler observes exactly one dismiss per external
close, and none while the popup stays open.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
from punt_lux.display.renderers.imgui.modal import ImGuiModalRenderer
from punt_lux.display.server import DisplayServer
from punt_lux.domain.container_interaction import ModalClosed
from punt_lux.protocol.elements.modal import ModalElement

if TYPE_CHECKING:
    import pytest


def _factory() -> ImGuiRendererFactory:
    raw_dir = tempfile.mkdtemp(prefix="lux-")
    server = DisplayServer(socket_path=str(Path(raw_dir) / "display.sock"))
    factory = server._imgui_renderer_factory
    assert isinstance(factory, ImGuiRendererFactory)
    return factory


def _capturing_modal(*, open: bool) -> tuple[ModalElement, list[ModalClosed]]:
    """Return a modal whose ModalClosed fires append to the returned list."""
    modal = ModalElement(id="m", title="Confirm", open=open)
    seen: list[ModalClosed] = []
    modal.add_handler(ModalClosed, seen.append)
    return modal, seen


def _patch(monkeypatch: pytest.MonkeyPatch, imgui: MagicMock) -> None:
    # Default: focused popup, no key pressed — so the Escape check is inert
    # unless a test opts in (a bare MagicMock returns a truthy key-press).
    imgui.is_window_focused.return_value = True
    imgui.is_key_pressed.return_value = False
    monkeypatch.setattr("punt_lux.display.renderers.imgui.modal.imgui", imgui)


def test_open_frame_opens_popup(monkeypatch: pytest.MonkeyPatch) -> None:
    imgui = MagicMock()
    imgui.begin_popup_modal.return_value = (True, True)
    _patch(monkeypatch, imgui)
    modal, seen = _capturing_modal(open=True)
    factory = _factory()

    renderer = ImGuiModalRenderer(modal, factory)
    visible = renderer.begin()
    renderer.end(opened=visible)

    assert visible is True
    imgui.open_popup.assert_called_once_with("Confirm###m")
    imgui.end_popup.assert_called_once()
    assert factory.widget_state.get("m__open") == 1
    assert seen == []


def test_seeds_minimum_width_before_opening_the_popup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The adapter floors the popup width before ``begin_popup_modal``.

    Without a size seed ImGui auto-sizes the modal to its minimal content width
    and the ABC text renderer's work-rect wrapping collapses it to a needle. The
    constraint (min width, unbounded max) must be issued before the popup is
    created, or ImGui has already sized it.
    """
    imgui = MagicMock()
    imgui.begin_popup_modal.return_value = (True, True)
    _patch(monkeypatch, imgui)
    modal, _ = _capturing_modal(open=True)
    factory = _factory()

    ImGuiModalRenderer(modal, factory).begin()

    imgui.set_next_window_size_constraints.assert_called_once()
    (size_min, _size_max), _kwargs = imgui.set_next_window_size_constraints.call_args
    assert size_min == (320.0, 0.0)  # min width floor, height auto
    names = [call[0] for call in imgui.mock_calls]
    assert names.index("set_next_window_size_constraints") < names.index(
        "begin_popup_modal"
    )


def test_close_button_fires_one_modal_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The title-bar ✕ dismisses: begin_popup_modal reports the popup not-visible.

    The ✕ is the only gesture ImGui resolves itself — it stops returning visible.
    """
    imgui = MagicMock()
    _patch(monkeypatch, imgui)
    modal, seen = _capturing_modal(open=True)
    factory = _factory()

    # Frame 1: the agent opens the modal.
    imgui.begin_popup_modal.return_value = (True, True)
    first = ImGuiModalRenderer(modal, factory)
    first.end(opened=first.begin())
    assert seen == []

    # Frame 2: the user clicks the ✕ — begin_popup_modal reports it not-visible.
    imgui.begin_popup_modal.return_value = (False, False)
    second = ImGuiModalRenderer(modal, factory)
    second.end(opened=second.begin())

    assert factory.widget_state.get("m__open") == 0
    assert factory.widget_state.get("m__dismissed") == 1
    assert len(seen) == 1
    assert seen[0].element_id == "m"


def test_escape_key_dismisses(monkeypatch: pytest.MonkeyPatch) -> None:
    """Escape while the popup is focused dismisses — the adapter resolves it.

    Real ImGui does not close a modal on Escape by default; the adapter detects
    the key and routes one ModalClosed to the Hub, closing the popup.
    """
    imgui = MagicMock()
    imgui.begin_popup_modal.return_value = (True, True)  # stays visible this frame
    _patch(monkeypatch, imgui)
    imgui.is_key_pressed.return_value = True  # Escape pressed
    modal, seen = _capturing_modal(open=True)
    factory = _factory()

    renderer = ImGuiModalRenderer(modal, factory)
    renderer.end(opened=renderer.begin())

    assert len(seen) == 1
    assert seen[0].element_id == "m"
    imgui.close_current_popup.assert_called_once()
    assert factory.widget_state.get("m__dismissed") == 1


def test_outside_click_does_not_dismiss(monkeypatch: pytest.MonkeyPatch) -> None:
    """A modal blocks outside clicks — it stays open, no ModalClosed fires.

    Popover-vs-modal semantics, chosen not missed: ImGui keeps the modal popup
    visible on an outside click (begin_popup_modal keeps returning visible) and
    no Escape/✕ gesture occurred, so nothing dismisses.
    """
    imgui = MagicMock()
    imgui.begin_popup_modal.return_value = (True, True)  # stays visible
    _patch(monkeypatch, imgui)  # is_key_pressed=False → no Escape
    modal, seen = _capturing_modal(open=True)
    factory = _factory()

    for _ in range(2):  # two frames of background clicks
        renderer = ImGuiModalRenderer(modal, factory)
        renderer.end(opened=renderer.begin())

    assert seen == []
    imgui.close_current_popup.assert_not_called()
    assert factory.widget_state.get("m__open") == 1  # still open


def test_closed_modal_does_not_open(monkeypatch: pytest.MonkeyPatch) -> None:
    imgui = MagicMock()
    imgui.begin_popup_modal.return_value = (False, False)
    _patch(monkeypatch, imgui)
    modal, seen = _capturing_modal(open=False)
    factory = _factory()

    renderer = ImGuiModalRenderer(modal, factory)
    visible = renderer.begin()
    renderer.end(opened=visible)

    assert visible is False
    imgui.open_popup.assert_not_called()
    assert seen == []


def test_default_title_falls_back_to_id(monkeypatch: pytest.MonkeyPatch) -> None:
    imgui = MagicMock()
    imgui.begin_popup_modal.return_value = (False, False)
    _patch(monkeypatch, imgui)
    modal = ModalElement(id="m", open=True)
    factory = _factory()

    ImGuiModalRenderer(modal, factory).begin()

    imgui.begin_popup_modal.assert_called_once_with("m###m", True)


class _IdentityImgui:
    """Minimal ImGui fake modeling ``##`` vs ``###`` popup-identity semantics.

    ImGui derives a popup's identity from the label string: ``"Title##id"`` hashes
    the whole string (so the label is part of the identity), while ``"Title###id"``
    hashes only the part after ``###`` (identity is the id alone). This fake keys
    the open set on that identity so a title change is only "still open" when the
    identity is stable — reproducing the real dismissal bug the ``###`` fix guards.
    """

    FLT_MAX = 3.4028234663852886e38
    Key = SimpleNamespace(escape=526)

    def __init__(self) -> None:
        self._open: set[str] = set()

    @staticmethod
    def _identity(popup_id: str) -> str:
        return popup_id.split("###", 1)[1] if "###" in popup_id else popup_id

    def set_next_window_size_constraints(
        self, _size_min: tuple[float, float], _size_max: tuple[float, float]
    ) -> None:
        return None

    def is_window_focused(self) -> bool:
        return True

    def is_key_pressed(self, _key: int) -> bool:
        return False  # this fake exercises identity semantics, not Escape

    def close_current_popup(self) -> None:
        return None

    def open_popup(self, popup_id: str) -> None:
        self._open.add(self._identity(popup_id))

    def begin_popup_modal(self, popup_id: str, _closable: bool) -> tuple[bool, bool]:
        return (self._identity(popup_id) in self._open, True)

    def end_popup(self) -> None:
        return None


def test_title_change_on_open_modal_does_not_dismiss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Renaming an open modal keeps it open — no spurious ModalClosed.

    The ``###`` identity pins the popup to the element id, so a ``_set_title``
    patch (or a re-push under a new title) does not re-hash the popup and make
    ImGui report it closed. Under the old ``##`` identity this test fires a
    ModalClosed — the exact dismiss-on-rename bug.
    """
    monkeypatch.setattr(
        "punt_lux.display.renderers.imgui.modal.imgui", _IdentityImgui()
    )
    modal, seen = _capturing_modal(open=True)
    factory = _factory()

    # Frame 1: open the modal.
    first = ImGuiModalRenderer(modal, factory)
    first.end(opened=first.begin())
    assert seen == []
    assert factory.widget_state.get("m__open") == 1

    # Frame 2: rename the still-open modal via the patch path, then re-render.
    modal.apply_patch({"title": "Renamed"})
    second = ImGuiModalRenderer(modal, factory)
    second.end(opened=second.begin())

    assert seen == []  # not dismissed by the rename
    assert factory.widget_state.get("m__open") == 1  # still latched open
    assert factory.widget_state.get("m__dismissed") in (None, 0)
