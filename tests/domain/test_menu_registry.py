"""HubMenuRegistry — the session-keyed agent menu bar, live-composed and stamped.

The registry keys each session's bar by the owning ``ConnectionId``, so two
sessions never clobber and a departed session's bar leaves the composed snapshot.
``wire_snapshot`` composes only the live sessions' bars and stamps each leaf id
``owner<US>item_id`` so a click round-trips to the owner.
"""

from __future__ import annotations

from punt_lux.domain.hub.connection_scoped_id import ConnectionScopedId
from punt_lux.domain.hub.hub_clients import HubClientRegistry
from punt_lux.domain.hub.menu_models import Menu, MenuAction
from punt_lux.domain.hub.menu_registry import HubMenuRegistry
from punt_lux.domain.hub.session_callback import MenuLeaf
from punt_lux.domain.ids import ConnectionId


def _live_registry() -> tuple[HubMenuRegistry, HubClientRegistry]:
    clients = HubClientRegistry()
    return HubMenuRegistry(clients), clients


def test_two_sessions_do_not_clobber_each_other() -> None:
    reg, clients = _live_registry()
    a, b = ConnectionId("sess-a"), ConnectionId("sess-b")
    clients.record(a)
    clients.record(b)
    reg.set_menus(a, [Menu(label="Tools", items=[MenuAction(id="run", label="Run")])])
    reg.set_menus(b, [Menu(label="Edit", items=[MenuAction(id="undo", label="Undo")])])

    labels = {menu.label for menu in reg.menu_bar()}
    assert labels == {"Tools", "Edit"}


def test_a_departed_session_bar_leaves_the_live_composition() -> None:
    reg, clients = _live_registry()
    live, gone = ConnectionId("live"), ConnectionId("gone")
    clients.record(live)
    clients.record(gone)
    reg.set_menus(live, [Menu(label="Live", items=[])])
    reg.set_menus(gone, [Menu(label="Gone", items=[])])

    clients.discard(gone)  # the session departs the live set

    assert [menu.label for menu in reg.menu_bar()] == ["Live"]
    assert [menu["label"] for menu in reg.wire_snapshot()] == ["Live"]


def test_wire_snapshot_stamps_each_leaf_id_with_its_owner() -> None:
    reg, clients = _live_registry()
    owner = ConnectionId("owner-1")
    clients.record(owner)
    reg.set_menus(
        owner,
        [Menu(label="Tools", items=[MenuAction(id="run", label="Run", shortcut="F5")])],
    )

    wire = reg.wire_snapshot()
    items = wire[0]["items"]
    assert isinstance(items, list)
    stamped = MenuLeaf("menu", owner, "run").wire_id
    assert items[0] == {"label": "Run", "id": stamped, "shortcut": "F5"}


def test_wire_snapshot_carries_a_frame_id_through_to_the_display() -> None:
    # gap (a) end to end: a frame-bound item's frame_id is OWNER-COMPOSED into the
    # snapshot the display receives — byte-identical to the scene frame key
    # ScenePresentation composes for the same owner, so raise_frame finds it.
    reg, clients = _live_registry()
    owner = ConnectionId("owner-frame")
    clients.record(owner)
    reg.set_menus(
        owner,
        [
            Menu(
                label="Tools",
                items=[MenuAction(id="run", label="Run", frame_id="dash")],
            )
        ],
    )

    items = reg.wire_snapshot()[0]["items"]
    assert isinstance(items, list)
    assert items[0] == {
        "label": "Run",
        "id": MenuLeaf("menu", owner, "run").wire_id,
        "frame_id": ConnectionScopedId.compose(owner, "dash"),
    }


def test_two_sessions_same_labelled_menu_carry_distinct_owner_identity() -> None:
    # gap-a-class collision at the heading level: two sessions both name a "Tools"
    # menu. The composed snapshot carries each heading's owner so the display keys
    # them apart, while the visible label stays verbatim for both.
    reg, clients = _live_registry()
    a, b = ConnectionId("sess-a"), ConnectionId("sess-b")
    clients.record(a)
    clients.record(b)
    reg.set_menus(a, [Menu(label="Tools", items=[])])
    reg.set_menus(b, [Menu(label="Tools", items=[])])

    by_owner = {menu["owner"]: menu["label"] for menu in reg.wire_snapshot()}
    assert by_owner == {"sess-a": "Tools", "sess-b": "Tools"}


def test_set_menus_replaces_only_the_owning_sessions_bar() -> None:
    reg, clients = _live_registry()
    owner = ConnectionId("owner-2")
    clients.record(owner)
    reg.set_menus(
        owner, [Menu(label="File", items=[MenuAction(id="open", label="Open")])]
    )
    reg.set_menus(
        owner, [Menu(label="Edit", items=[MenuAction(id="undo", label="Undo")])]
    )

    assert [menu.label for menu in reg.menu_bar()] == ["Edit"]


def test_drop_session_prunes_the_bar() -> None:
    reg, clients = _live_registry()
    owner = ConnectionId("owner-3")
    clients.record(owner)
    reg.set_menus(owner, [Menu(label="File", items=[])])

    reg.drop_session(owner)

    assert reg.menu_bar() == []
    assert reg.wire_snapshot() == ()


def test_menu_bar_returns_copies_the_caller_cannot_mutate() -> None:
    reg, clients = _live_registry()
    owner = ConnectionId("owner-4")
    clients.record(owner)
    reg.set_menus(
        owner, [Menu(label="File", items=[MenuAction(id="open", label="Open")])]
    )

    returned = reg.menu_bar()
    returned[0].items.append(MenuAction(id="ghost", label="Ghost"))

    stored_items = reg.menu_bar()[0].items
    assert len(stored_items) == 1
    first = stored_items[0]
    assert isinstance(first, MenuAction)
    assert first.id == "open"


def test_set_menus_snapshots_against_later_mutation_of_the_request() -> None:
    # Ingress aliasing: a frozen Menu does not freeze its items list, so storing
    # the caller's object by reference would let a later mutation of the original
    # request reach the stored — and about-to-be-sent — tree. set_menus deep-copies
    # on ingress. Fail-on-current if it stored by reference: the appended "ghost"
    # leaks into wire_snapshot.
    reg, clients = _live_registry()
    owner = ConnectionId("owner-mut")
    clients.record(owner)
    original = Menu(label="Tools", items=[MenuAction(id="run", label="Run")])
    reg.set_menus(owner, [original])

    original.items.append(MenuAction(id="ghost", label="Ghost"))

    items = reg.wire_snapshot()[0]["items"]
    assert isinstance(items, list)
    assert [item["id"] for item in items] == [MenuLeaf("menu", owner, "run").wire_id]


def test_wire_snapshot_of_an_empty_registry_is_empty() -> None:
    reg, _clients = _live_registry()
    assert reg.wire_snapshot() == ()
