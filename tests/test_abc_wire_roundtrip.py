"""End-to-end wire tests for the 4 Element-ABC exemplars.

Two real boundaries, no stubs:

- The native-pickle scene wire (``protocol/messages/scene.py`` ``_scene_to_dict`` /
  ``_scene_from_dict``): build -> ``message_to_dict`` -> assert ``_pickled`` ->
  ``message_from_dict`` -> compare-equal, for all four kinds including a dialog
  (which previously had no scene roundtrip) and a dialog with a child.

- The full D21 interaction leg for an interactive kind: the Display wrapper
  produces the ``RemoteEventHandlerInvocation`` (never hand-built), it crosses a
  real socket, and the Hub resolves + fires the real handler on its
  authoritative copy exactly once.
"""

from __future__ import annotations

import socket
from dataclasses import replace

import pytest

from punt_lux.domain.display import Display
from punt_lux.domain.ids import ElementId, SceneId
from punt_lux.domain.interaction import ValueChanged
from punt_lux.domain.update import AddElement
from punt_lux.protocol import SceneMessage, recv_message, send_message
from punt_lux.protocol.elements import (
    ButtonElement,
    CheckboxElement,
    DialogElement,
    Element,
    TextElement,
)
from punt_lux.protocol.messages import message_from_dict, message_to_dict
from punt_lux.protocol.messages.remote_invocation import RemoteEventHandlerInvocation

# -- native-pickle scene roundtrip for all four exemplars -------------------


def _roundtrip(element: Element) -> Element:
    """Ship ``element`` through the real scene wire and return the restored one."""
    wire = message_to_dict(SceneMessage(id="s1", elements=[element]))
    assert "_pickled" in wire["elements"][0], "ABC element must use native pickle wire"
    restored = message_from_dict(wire)
    assert isinstance(restored, SceneMessage)
    return restored.elements[0]


def test_text_native_wire_roundtrip() -> None:
    restored = _roundtrip(
        TextElement(id="t1", content="hi", style="heading", tooltip="tip", color="#F00")
    )
    assert isinstance(restored, TextElement)
    assert restored.content == "hi"
    assert restored.style == "heading"
    assert restored.tooltip == "tip"
    assert restored.color == "#F00"


def test_button_native_wire_roundtrip() -> None:
    restored = _roundtrip(
        ButtonElement(
            id="b1",
            label="OK",
            action="submit",
            disabled=True,
            arrow="left",
            tooltip="tip",
        )
    )
    assert isinstance(restored, ButtonElement)
    assert restored.label == "OK"
    assert restored.action == "submit"
    assert restored.disabled is True
    assert restored.arrow == "left"
    assert restored.tooltip == "tip"


def test_checkbox_native_wire_roundtrip() -> None:
    restored = _roundtrip(
        CheckboxElement(id="c1", label="Bold", value=True, tooltip="tip")
    )
    assert isinstance(restored, CheckboxElement)
    assert restored.label == "Bold"
    assert restored.value is True
    assert restored.tooltip == "tip"


def test_dialog_native_wire_roundtrip() -> None:
    """Dialog scene roundtrip — the exemplar that previously had none."""
    restored = _roundtrip(DialogElement(id="d1", title="Confirm", tooltip="sure?"))
    assert isinstance(restored, DialogElement)
    assert restored.title == "Confirm"
    assert restored.tooltip == "sure?"
    assert restored.visible is True


def test_dialog_native_wire_roundtrip_preserves_children() -> None:
    """The composite exemplar's child subtree survives the pickle wire."""
    dialog = DialogElement(id="d1", title="Confirm")
    dialog.install_children((ButtonElement(id="ok", label="OK"),))
    restored = _roundtrip(dialog)
    assert isinstance(restored, DialogElement)
    assert len(restored.children) == 1
    child = restored.children[0]
    assert isinstance(child, ButtonElement)
    assert child.id == "ok"


# -- full Display-wrap -> real socket -> Hub dispatch leg -------------------


def test_full_wrap_socket_hub_leg_fires_once_on_authoritative_copy() -> None:
    """Prove the D21 property across a real wire, not in-process.

    The Display-side wrapper (``wrap_handlers_for_remote``) produces the
    ``RemoteEventHandlerInvocation`` — it is NOT hand-constructed. It crosses a
    real ``socket.socketpair`` via the production framing (``send_message`` /
    ``recv_message``). The Hub resolves the element in its authoritative store
    and fires the real handler exactly once; the Display-side handler never
    runs locally.
    """
    # -- Hub side: authoritative store holding the real handler ---------------
    hub = Display()
    alice = hub.connect_client(name="alice")
    hub.add_scene(SceneId("s1"))
    hub_checkbox = CheckboxElement(id="c1", label="Bold", value=False)
    hub.apply(alice, AddElement(scene_id=SceneId("s1"), element=hub_checkbox))
    fired: list[ValueChanged] = []
    hub_checkbox.add_handler(ValueChanged, fired.append)

    # -- Display side: a copy whose handlers are wrapped for remote -----------
    display_checkbox = CheckboxElement(id="c1", label="Bold", value=False)
    display_checkbox.add_handler(
        ValueChanged,
        lambda _e: pytest.fail("display-side handler must not run locally"),
    )
    display_end, hub_end = socket.socketpair()

    def send_fn(invocation: RemoteEventHandlerInvocation) -> None:
        # The display stamps the active scene_id (as DisplayServer._emit_event
        # does) then writes the invocation over the real socket.
        send_message(display_end, replace(invocation, scene_id="s1"))

    display_checkbox.wrap_handlers_for_remote(send_fn)

    # A toggle on the Display copy — the wrapper emits the invocation.
    display_checkbox.fire(
        ValueChanged(
            scene_id=SceneId("s1"),
            element_id=ElementId("c1"),
            owner_id=alice,
            value=True,
        )
    )

    # -- The invocation crosses the wire and the Hub consumes it --------------
    invocation = recv_message(hub_end, timeout=2.0)
    assert isinstance(invocation, RemoteEventHandlerInvocation)
    assert invocation.event_kind == "value_changed"

    event = hub.interact(alice, invocation)

    assert isinstance(event, ValueChanged)
    assert event.value is True
    assert fired == [event]  # fired once, on the Hub's authoritative copy

    display_end.close()
    hub_end.close()
