"""Connection-lifecycle cleanup — D7 / D17 / Commit 8 invariants.

Two invariants verified here:

- An orphan handler firing after its connection's subscriptions are
  gone is a safe no-op — the publish snapshots an empty subscriber set
  and returns zero. The independence of the per-Element handler
  registry and the per-connection subscription registry is what makes
  this trivial.
- ``Display.interact`` rejects a wire ``InteractionMessage`` whose
  ``client_id`` has been dropped from the clients registry with
  ``UnknownClientError`` — the disconnect path's call to
  ``HubDisplay.drop_connection`` (and the parallel
  ``Display.disconnect_client``) closes the gate.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Self

import pytest

from punt_lux.domain.display import Display
from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId, Topic
from punt_lux.domain.interaction_errors import UnknownClientError
from punt_lux.domain.update import AddElement
from punt_lux.protocol.messages.interaction import InteractionMessage
from punt_lux.protocol.messages.observer import ObserverMessage


@dataclass(frozen=True, slots=True)
class _Button:
    """Stand-in element for the interact-rejects test."""

    id: ElementId
    label: str = ""
    kind: Literal["button"] = "button"
    tooltip: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {"id": str(self.id), "kind": self.kind, "label": self.label}

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        return cls(id=ElementId(str(d["id"])), label=str(d.get("label", "")))


def test_orphan_handler_publish_after_disconnect_is_safe_noop() -> None:
    """A publish from a handler fired after the subscriber's connection
    drops returns zero subscribers and does not raise (D17)."""
    isolated_hub = Hub()
    received: list[ObserverMessage] = []

    def _writer(message: ObserverMessage) -> None:
        received.append(message)

    connection = ConnectionId("orphan-1")
    topic = Topic("save.pressed")

    isolated_hub.register_writer(connection, _writer)
    isolated_hub.subscribe(connection, topic)

    isolated_hub.on_disconnect(connection)

    delivered = isolated_hub.publish(connection, topic, {"k": "v"})

    assert delivered == 0
    assert received == []


def test_display_interact_rejects_disconnected_client_with_unknown_client_error() -> (
    None
):
    """After ``drop_connection`` the client gate refuses
    ``Display.interact`` calls with ``UnknownClientError``."""
    display = Display()
    hub_display = HubDisplay()

    client_id = display.connect_client(name="lifecycle-agent")
    connection_id = ConnectionId(str(client_id))
    hub_display.register_client(connection_id)

    scene_id = SceneId("lifecycle-scene")
    element_id = ElementId("btn-1")
    display.add_scene(scene_id)
    button = _Button(id=element_id, label="go")
    display.apply(
        client_id, AddElement(scene_id=scene_id, element=button, parent_id=None)
    )
    hub_display.apply(
        connection_id,
        AddElement(scene_id=scene_id, element=button, parent_id=None),
    )

    assert hub_display.is_client(connection_id)
    assert display.is_client(client_id)

    hub_display.drop_connection(connection_id)
    display.disconnect_client(client_id)

    assert not hub_display.is_client(connection_id)
    assert not display.is_client(client_id)
    assert hub_display.elements_owned_by(connection_id) == ()

    msg = InteractionMessage(
        element_id=str(element_id),
        action="click",
        scene_id=str(scene_id),
        value=True,
    )
    with pytest.raises(UnknownClientError):
        display.interact(client_id, msg)
