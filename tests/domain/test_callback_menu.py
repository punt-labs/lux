"""CallbackMenu — the uniform session-then-callback menu build.

One submenu per identified live session that has callbacks, labeled from its
identity, callbacks as leaves — the same shape whatever the count, and two
sessions never merged. Unidentified sessions and sessions with no callbacks
contribute nothing, and each leaf id round-trips a click back to its session.
"""

from __future__ import annotations

from punt_lux.domain.hub.callback_menu import CallbackMenu
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.client_session import ClientSession
from punt_lux.domain.hub.menu_models import Menu, MenuAction
from punt_lux.domain.hub.session_callback import CallbackInvocation, SessionCallback
from punt_lux.domain.ids import ConnectionId


def _session(name: str, repo: str | None, *callbacks: SessionCallback) -> ClientSession:
    session = ClientSession(0.0).with_identity(
        ClientIdentity(kind="mcp-session", name=name, repo=repo)
    )
    for callback in callbacks:
        session = session.with_callback(callback)
    return session


def _beads() -> SessionCallback:
    return SessionCallback(id="beads", label="Beads")


def test_a_one_callback_session_is_a_single_leaf_submenu() -> None:
    conn = ConnectionId("vox")
    menus = CallbackMenu.from_sessions({conn: _session("vox", "/w/vox", _beads())})
    assert len(menus) == 1
    submenu = menus[0]
    assert submenu.label == "vox — /w/vox"
    assert submenu.items == [
        MenuAction(id=CallbackInvocation(conn, "beads").menu_id, label="Beads")
    ]


def test_a_many_callback_session_has_the_same_shape() -> None:
    conn = ConnectionId("vox")
    session = _session(
        "vox",
        "/w/vox",
        SessionCallback(id="beads", label="Beads"),
        SessionCallback(id="build", label="Build"),
    )
    menus = CallbackMenu.from_sessions({conn: session})
    # One submenu, several leaves — no flattening, no count-dependent shape.
    assert len(menus) == 1
    labels = [leaf.label for leaf in menus[0].items if isinstance(leaf, MenuAction)]
    assert labels == ["Beads", "Build"]  # sorted


def test_two_sessions_with_the_same_callback_are_never_merged() -> None:
    vox, lux = ConnectionId("vox"), ConnectionId("lux")
    menus = CallbackMenu.from_sessions(
        {
            vox: _session("claude", "/w/vox", _beads()),
            lux: _session("claude", "/w/lux", _beads()),
        }
    )
    # Same name, same callback id, different repos: two distinct submenus.
    assert len(menus) == 2
    assert {menu.label for menu in menus} == {"claude — /w/vox", "claude — /w/lux"}
    # The leaf ids carry their own session, so a click routes to the right one.
    leaf_ids = {
        menu.items[0].id for menu in menus if isinstance(menu.items[0], MenuAction)
    }
    assert leaf_ids == {
        CallbackInvocation(vox, "beads").menu_id,
        CallbackInvocation(lux, "beads").menu_id,
    }


def test_an_unidentified_session_contributes_no_submenu() -> None:
    bare = ClientSession(0.0).with_callback(_beads())  # never identified
    assert CallbackMenu.from_sessions({ConnectionId("bare"): bare}) == []


def test_an_identified_session_with_no_callbacks_contributes_nothing() -> None:
    session = _session("vox", "/w/vox")  # identified, but registered no callback
    assert CallbackMenu.from_sessions({ConnectionId("vox"): session}) == []


def test_a_headless_session_label_carries_no_repo() -> None:
    session = _session("lux-cli", None, _beads())  # a headless CLI declares no repo
    menus = CallbackMenu.from_sessions({ConnectionId("cli"): session})
    assert menus[0].label == "lux-cli"


def test_the_leaf_id_round_trips_to_the_owning_session() -> None:
    conn = ConnectionId("vox")
    menus = CallbackMenu.from_sessions({conn: _session("vox", "/w/vox", _beads())})
    leaf = menus[0].items[0]
    assert isinstance(leaf, MenuAction)
    assert CallbackInvocation.from_menu_id(leaf.id) == CallbackInvocation(conn, "beads")


def test_submenus_are_ordered_by_label() -> None:
    menus = CallbackMenu.from_sessions(
        {
            ConnectionId("q"): _session("quarry", "/w/quarry", _beads()),
            ConnectionId("l"): _session("lux", "/w/lux", _beads()),
        }
    )
    assert [menu.label for menu in menus] == ["lux — /w/lux", "quarry — /w/quarry"]


def test_every_submenu_is_a_menu() -> None:
    menus = CallbackMenu.from_sessions(
        {ConnectionId("vox"): _session("vox", "/w/vox", _beads())}
    )
    assert all(isinstance(menu, Menu) for menu in menus)


def test_replica_returns_the_live_submenus_as_wire() -> None:
    """CallbackMenuReplica composes the live sessions into wire submenus."""
    from punt_lux.domain.hub.callback_menu import CallbackMenuReplica
    from punt_lux.domain.hub.hub_clients import HubClientRegistry

    registry = HubClientRegistry()
    conn = ConnectionId("vox")
    registry.record(conn, ClientIdentity(kind="app", name="voxd"))
    registry.register_callback(conn, SessionCallback(id="music", label="Music"))

    wire = CallbackMenuReplica(registry).callback_menu_wire()

    assert wire == [
        {
            "label": "voxd",
            "items": [
                {"label": "Music", "id": CallbackInvocation(conn, "music").menu_id}
            ],
        }
    ]


def test_replica_is_empty_when_no_session_has_a_callback() -> None:
    from punt_lux.domain.hub.callback_menu import CallbackMenuReplica
    from punt_lux.domain.hub.hub_clients import HubClientRegistry

    registry = HubClientRegistry()
    registry.record(ConnectionId("lux"), ClientIdentity(kind="mcp-session", name="lux"))
    assert CallbackMenuReplica(registry).callback_menu_wire() == []
