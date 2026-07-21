"""HubMenuRegistry — one item per id across sessions, last write winning.

Two sessions registering the same tool_id must not leave the registry holding
two items with one id: that is the read/screen divergence class — the display
dedupes by id, so a registry that reports both disagrees with what is rendered.
The id belongs to the session that wrote it last, and that session's disconnect
is what removes it.
"""

from __future__ import annotations

from punt_lux.domain.hub.menu_models import Menu, MenuAction
from punt_lux.domain.hub.menu_registry import HubMenuRegistry
from punt_lux.domain.ids import ConnectionId

_A = ConnectionId("session-a")
_B = ConnectionId("session-b")


def test_same_id_across_sessions_dedupes_to_the_later_write() -> None:
    reg = HubMenuRegistry()
    reg.register_item(_A, MenuAction(id="run", label="Run (A)"))
    reg.register_item(_B, MenuAction(id="run", label="Run (B)"))

    items = reg.registered_items()
    # One item survives — the later write — matching the display's own dedupe.
    assert [item.id for item in items] == ["run"]
    assert items[0].label == "Run (B)"


def test_the_earlier_sessions_disconnect_does_not_remove_a_stolen_id() -> None:
    reg = HubMenuRegistry()
    reg.register_item(_A, MenuAction(id="run", label="Run (A)"))
    reg.register_item(_B, MenuAction(id="run", label="Run (B)"))

    reg.drop(_A)  # A no longer owns "run" — B claimed it

    items = reg.registered_items()
    assert [item.id for item in items] == ["run"]
    assert items[0].label == "Run (B)"


def test_the_owning_sessions_disconnect_removes_the_id() -> None:
    reg = HubMenuRegistry()
    reg.register_item(_A, MenuAction(id="run", label="Run (A)"))
    reg.register_item(_B, MenuAction(id="run", label="Run (B)"))

    reg.drop(_B)  # B owns "run" now — its disconnect removes it

    assert reg.registered_items() == []


def test_wire_snapshot_carries_one_item_per_id() -> None:
    reg = HubMenuRegistry()
    reg.register_item(_A, MenuAction(id="run", label="Run (A)"))
    reg.register_item(_B, MenuAction(id="run", label="Run (B)"))
    reg.register_item(_A, MenuAction(id="build", label="Build"))

    ids = [str(item["id"]) for item in reg.wire_snapshot().items]
    assert sorted(ids) == ["build", "run"]


def test_distinct_ids_from_two_sessions_both_survive() -> None:
    reg = HubMenuRegistry()
    reg.register_item(_A, MenuAction(id="run", label="Run"))
    reg.register_item(_B, MenuAction(id="build", label="Build"))

    assert sorted(item.id for item in reg.registered_items()) == ["build", "run"]


def test_menu_bar_returns_copies_the_caller_cannot_mutate() -> None:
    reg = HubMenuRegistry()
    reg.set_menus([Menu(label="File", items=[MenuAction(id="open", label="Open")])])

    returned = reg.menu_bar()
    # frozen=True does not freeze Menu.items (a list); appending to a returned
    # menu's items must not reach the registry's stored bar.
    returned[0].items.append(MenuAction(id="ghost", label="Ghost"))

    stored_items = reg.menu_bar()[0].items
    assert len(stored_items) == 1
    first = stored_items[0]
    assert isinstance(first, MenuAction)
    assert first.id == "open"


def test_registered_items_hands_out_copies_not_the_stored_models() -> None:
    reg = HubMenuRegistry()
    reg.register_item(_A, MenuAction(id="run", label="Run"))

    # Each read returns a fresh copy, never the stored instance — MenuAction is
    # frozen with scalar fields today, but the read is isolated regardless of
    # what fields it grows, matching menu_bar.
    assert reg.registered_items()[0] is not reg.registered_items()[0]
