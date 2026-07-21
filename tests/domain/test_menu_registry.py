"""HubMenuRegistry — one item per id across sessions, last write winning.

Two sessions registering the same tool_id must not leave the registry holding
two items with one id: that is the read/screen divergence class — the display
dedupes by id, so a registry that reports both disagrees with what is rendered.
The id belongs to the session that wrote it last, and that session's disconnect
is what removes it.
"""

from __future__ import annotations

from punt_lux.domain.hub.menu_models import MenuAction
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
