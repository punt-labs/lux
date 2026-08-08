"""Connection-lifecycle cleanup invariants.

Two invariants verified here:

- An orphan handler firing after its connection's subscriptions are
  gone is a safe no-op — the publish snapshots an empty subscriber set
  and returns zero. The independence of the per-Element handler
  registry and the per-connection subscription registry is what makes
  this trivial.
- ``HubDisplay.drop_connection`` forgets the departing session without
  disturbing the UI it installed: the elements stay indexed and owned, and
  a display click on them still reaches its handler, because a
  ``RemoteEventHandlerInvocation`` names no caller for the Hub to gate on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId, Topic
from punt_lux.domain.interaction import ButtonClicked
from punt_lux.protocol.elements import ButtonElement
from punt_lux.protocol.messages.observer import ObserverMessage
from tests.hub_harness import IsolatedHub

if TYPE_CHECKING:
    import pytest


def test_orphan_handler_publish_after_disconnect_is_safe_noop() -> None:
    """A publish from a handler fired after the subscriber's connection
    drops returns zero subscribers and does not raise."""
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


def test_dropped_connection_keeps_its_elements_and_their_clicks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A session's UI outlives the session, clicks included.

    ``drop_connection`` deregisters the client and nothing else: the elements it
    installed stay indexed and still owned by its id, so a later frame close,
    clear, or TTL can remove them. A click that arrives afterwards still fires,
    because the invocation carries no caller identity — the Hub has no caller to
    compare against the owner. That is the documented state of the dispatch
    path, recorded here so a future identity gate has a test to change rather
    than a silent gap to discover.
    """
    hub = IsolatedHub(monkeypatch)
    connection_id = hub.connect("lifecycle-agent")
    scene_id = SceneId("lifecycle-scene")
    element_id = ElementId("btn-1")

    button = ButtonElement(id=str(element_id), label="go")
    fired: list[ButtonClicked] = []
    button.add_handler(ButtonClicked, fired.append)
    hub.install(connection_id, scene_id, button)
    assert hub.display.is_client(connection_id)

    hub.display.drop_connection(connection_id)

    assert not hub.display.is_client(connection_id)
    assert hub.display.elements_owned_by(connection_id) != ()
    assert hub.display.resolve(scene_id, element_id) is button

    hub.click(scene_id, element_id)

    assert len(fired) == 1
