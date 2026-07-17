"""ModalRenderer latches open/dismiss state and emits a ``closed`` event.

The renderer under test is real, driven through its injected ``WidgetState``;
only the ImGui backend is faked (a mock at the render boundary). The
open → dismiss cycle transitions the latch keys and emits exactly one
``closed`` event — behaviour identical to the pre-extraction inline body.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, call

from punt_lux.display.renderers.leaf_widget_renderer import LeafWidgetRenderer
from punt_lux.display.renderers.modal_renderer import ModalRenderer
from punt_lux.protocol.elements.layout import ModalElement
from punt_lux.protocol.elements.text import TextElement
from punt_lux.scene.widget_state import WidgetState

if TYPE_CHECKING:
    import pytest

    from punt_lux.protocol.messages.remote_invocation import (
        RemoteEventHandlerInvocation,
    )


def _patch(monkeypatch: pytest.MonkeyPatch, imgui: MagicMock) -> None:
    monkeypatch.setattr("punt_lux.display.renderers.modal_renderer.imgui", imgui)


def test_modal_renderer_satisfies_leaf_widget_protocol() -> None:
    # The runtime family contract: a renderer structurally satisfies the
    # single-method Protocol. Bound through ``object`` because each renderer
    # narrows ``render``'s element type, so the check is a runtime one.
    renderer: object = ModalRenderer(
        WidgetState(), lambda _msg: None, lambda _child: None
    )
    assert isinstance(renderer, LeafWidgetRenderer)


def test_open_frame_opens_popup_and_renders_children(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imgui = MagicMock()
    imgui.begin_popup_modal.return_value = (True, True)
    _patch(monkeypatch, imgui)
    ws = WidgetState()
    children: list[object] = []
    child = TextElement(id="c", content="hi")
    modal = ModalElement(id="m", title="Confirm", open=True, children=[child])

    ModalRenderer(ws, lambda _msg: None, children.append).render(modal)

    imgui.open_popup.assert_called_once_with("Confirm##m")
    imgui.begin_popup_modal.assert_called_once_with("Confirm##m", True)
    assert ws.get("m__open") == 1
    assert children == [child]
    imgui.end_popup.assert_called_once()


def test_dismiss_cycle_latches_and_emits_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imgui = MagicMock()
    _patch(monkeypatch, imgui)
    ws = WidgetState()
    events: list[RemoteEventHandlerInvocation] = []
    modal = ModalElement(id="m", title="Confirm", open=True)
    renderer = ModalRenderer(ws, events.append, lambda _child: None)

    # Frame 1: agent opens the modal.
    imgui.begin_popup_modal.return_value = (True, True)
    renderer.render(modal)
    assert events == []

    # Frame 2: user dismisses (popup no longer visible) while open stays True.
    imgui.begin_popup_modal.return_value = (False, False)
    renderer.render(modal)

    assert ws.get("m__open") == 0
    assert ws.get("m__dismissed") == 1
    assert [e.action for e in events] == ["closed"]
    assert events[0].element_id == "m"
    assert events[0].value is None


def test_agent_close_clears_latches(monkeypatch: pytest.MonkeyPatch) -> None:
    imgui = MagicMock()
    _patch(monkeypatch, imgui)
    ws = WidgetState()
    ws.set("m__open", 1)
    ws.set("m__dismissed", 1)
    modal = ModalElement(id="m", title="Confirm", open=False)

    ModalRenderer(ws, lambda _msg: None, lambda _child: None).render(modal)

    assert ws.get("m__open") == 0
    assert ws.get("m__dismissed") == 0
    imgui.begin_popup_modal.assert_not_called()


def test_dismissed_modal_does_not_reopen(monkeypatch: pytest.MonkeyPatch) -> None:
    imgui = MagicMock()
    imgui.begin_popup_modal.return_value = (False, False)
    _patch(monkeypatch, imgui)
    ws = WidgetState()
    ws.set("m__dismissed", 1)  # user already dismissed, agent has not acked
    modal = ModalElement(id="m", title="Confirm", open=True)

    ModalRenderer(ws, lambda _msg: None, lambda _child: None).render(modal)

    imgui.open_popup.assert_not_called()


def test_default_title_falls_back_to_id(monkeypatch: pytest.MonkeyPatch) -> None:
    imgui = MagicMock()
    imgui.begin_popup_modal.return_value = (False, False)
    _patch(monkeypatch, imgui)

    ModalRenderer(WidgetState(), lambda _msg: None, lambda _child: None).render(
        ModalElement(id="m", open=True)
    )

    assert imgui.begin_popup_modal.call_args == call("m##m", True)
