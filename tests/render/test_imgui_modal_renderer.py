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
    imgui.open_popup.assert_called_once_with("Confirm##m")
    imgui.end_popup.assert_called_once()
    assert factory.widget_state.get("m__open") == 1
    assert seen == []


def test_external_close_fires_one_modal_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imgui = MagicMock()
    _patch(monkeypatch, imgui)
    modal, seen = _capturing_modal(open=True)
    factory = _factory()

    # Frame 1: the agent opens the modal.
    imgui.begin_popup_modal.return_value = (True, True)
    first = ImGuiModalRenderer(modal, factory)
    first.end(opened=first.begin())
    assert seen == []

    # Frame 2: the user dismisses (popup no longer visible) while open stays True.
    imgui.begin_popup_modal.return_value = (False, False)
    second = ImGuiModalRenderer(modal, factory)
    second.end(opened=second.begin())

    assert factory.widget_state.get("m__open") == 0
    assert factory.widget_state.get("m__dismissed") == 1
    assert len(seen) == 1
    assert seen[0].element_id == "m"


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

    imgui.begin_popup_modal.assert_called_once_with("m##m", True)
