"""disconnect_connection cleans the session but leaves its scenes standing.

A session's UI outlives the session (ruling: scenes survive session death). The
lifecycle entry point forgets the connection as a Hub client and fires the
transport sink so per-session resources (the MCP inbox, subscriptions) are
released — but it does NOT tear down the scenes the connection installed, so
nothing is blanked and there is no repaint to mark. Removal is a later, explicit
act: a user closing the frame, an agent clearing, or a frame TTL expiring.
"""

from __future__ import annotations

from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.lifecycle import disconnect_connection
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.protocol.elements.text import TextElement

_CONN = ConnectionId("c1")


def test_disconnect_leaves_the_sessions_scenes_standing() -> None:
    store = HubDisplay()
    store.register_client(_CONN)
    store.replace_scene(_CONN, SceneId("s1"), [TextElement(id="s1-root", content="x")])
    store.replace_scene(_CONN, SceneId("s2"), [TextElement(id="s2-root", content="y")])

    released: list[ConnectionId] = []
    disconnect_connection(_CONN, released.append, hub_display=store, hub=Hub())

    # Scenes survive session death — still installed, still owned by the id that
    # can later remove them (frame-close, clear, TTL).
    assert store.scene_roots(SceneId("s1"))
    assert store.scene_roots(SceneId("s2"))
    # The session leaves the client registry.
    assert not store.is_client(_CONN)
    # The transport sink still fires so the MCP inbox is released.
    assert released == [_CONN]


def test_disconnect_of_an_unknown_connection_still_releases_resources() -> None:
    store = HubDisplay()
    released: list[ConnectionId] = []
    disconnect_connection(_CONN, released.append, hub_display=store, hub=Hub())

    assert released == [_CONN]
