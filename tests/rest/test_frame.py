"""The frame routes -- close the caller's own frame, over the real facade.

Split out of ``test_display_routes.py`` to mirror the source split
(``rest/frame.py`` out of ``rest/display.py``, lux-03k6): closing a frame is
a Hub-side write with its own ownership rule, not a proxied display read.
"""

from __future__ import annotations

from urllib.parse import quote

from punt_lux.connection_identity import connection_for
from punt_lux.domain.hub.connection_scoped_id import ConnectionScopedId
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.id_separator import ID_SEPARATOR
from punt_lux.domain.ids import SceneId
from punt_lux.operations.display_reply import DisplayReplied

from ._fakes import DEFAULT_CONNECTION, StubPort, make_client

_TEXT = {"kind": "text", "id": "t1", "content": "hi"}


def test_close_frame_of_a_nonexistent_frame_is_not_found() -> None:
    # No caller ever showed anything into "f1" -- the route must not report a
    # blanket success for a frame it tore nothing down (lux-03k6).
    client = make_client(display_port=StubPort(DisplayReplied({})))
    resp = client.post("/display/frames/f1/close")
    assert resp.status_code == 404


def test_close_frame_removes_the_callers_own_frame() -> None:
    store = HubDisplay()
    client = make_client(display_port=StubPort(DisplayReplied({})), store=store)
    client.put(
        "/scenes/s1",
        json={"scene_id": "s1", "elements": [_TEXT], "frame": {"frame_id": "board"}},
    )

    resp = client.post("/display/frames/board/close")

    assert resp.status_code == 200
    assert resp.json() == {"kind": "ok"}
    scoped = SceneId(ConnectionScopedId.compose(DEFAULT_CONNECTION, "s1"))
    assert store.scene_roots(scoped) == []


def test_close_frame_of_another_connections_frame_is_not_found() -> None:
    # DES-086: a frame named by another connection's local id is
    # indistinguishable from one that never existed, so this is not_found
    # too -- and the other caller's scene is left standing.
    store = HubDisplay()
    owner_identity = {
        "X-Lux-Client-Kind": "cli",
        "X-Lux-Client-Name": "owner",
        "X-Lux-Client-Repo": "/w/owner",
    }
    owner_client = make_client(
        display_port=StubPort(DisplayReplied({})), store=store, identity=owner_identity
    )
    owner_client.put(
        "/scenes/s1",
        json={"scene_id": "s1", "elements": [_TEXT], "frame": {"frame_id": "board"}},
    )
    stranger_client = make_client(
        display_port=StubPort(DisplayReplied({})), store=store
    )

    resp = stranger_client.post("/display/frames/board/close")

    assert resp.status_code == 404
    owner_connection = connection_for(
        {"kind": "cli", "name": "owner", "repo": "/w/owner"}
    )
    scoped = SceneId(ConnectionScopedId.compose(owner_connection, "s1"))
    assert store.scene_roots(scoped) != []


def test_close_frame_of_a_malformed_frame_id_is_a_422_not_a_500() -> None:
    # A frame_id carrying the unit separator can never compose to a store key
    # (ConnectionScopedId.compose raises ValueError); the route must map that
    # to the caller's own invalid_request, not let it surface as a 500.
    client = make_client(display_port=StubPort(DisplayReplied({})))
    malformed = quote(f"a{ID_SEPARATOR}b", safe="")

    resp = client.post(f"/display/frames/{malformed}/close")

    assert resp.status_code == 422
