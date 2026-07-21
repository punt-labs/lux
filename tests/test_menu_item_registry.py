"""MenuItemRegistry — dedupe, declared-built-in preservation, and skip-on-collision."""

from __future__ import annotations

from punt_lux.menu_item_registry import MenuItemRegistry


def test_replace_agent_items_dedupes_a_repeated_id() -> None:
    reg = MenuItemRegistry()
    snapshot = reg.replace_agent_items(
        [{"id": "a", "label": "First"}, {"id": "a", "label": "Second"}]
    )
    # One "a" survives; the second write updated it in place.
    assert [i["id"] for i in snapshot] == ["a"]
    assert snapshot[0]["label"] == "Second"


def test_replace_agent_items_keeps_declared_builtins() -> None:
    reg = MenuItemRegistry()
    reg.declare({"id": "beads", "label": "Beads"})
    snapshot = reg.replace_agent_items([{"id": "x", "label": "X"}])
    assert [i["id"] for i in snapshot] == ["beads", "x"]


def test_replace_agent_items_never_overrides_a_declared_builtin() -> None:
    reg = MenuItemRegistry()
    reg.declare({"id": "beads", "label": "Beads"})
    snapshot = reg.replace_agent_items(
        [{"id": "beads", "label": "Hijack"}, {"id": "y", "label": "Y"}]
    )
    # The colliding agent item is dropped; the built-in keeps its label.
    assert [i["id"] for i in snapshot] == ["beads", "y"]
    beads = next(i for i in snapshot if i["id"] == "beads")
    assert beads["label"] == "Beads"


def test_replace_agent_items_drops_the_previous_agent_set() -> None:
    reg = MenuItemRegistry()
    reg.replace_agent_items([{"id": "old", "label": "Old"}])
    snapshot = reg.replace_agent_items([{"id": "new", "label": "New"}])
    # A replace is authoritative: the prior agent item is gone.
    assert [i["id"] for i in snapshot] == ["new"]


def test_declare_dedupes_and_snapshot_copies() -> None:
    reg = MenuItemRegistry()
    reg.declare({"id": "beads", "label": "Beads"})
    reg.declare({"id": "beads", "label": "Beads v2"})
    first = reg.snapshot()
    assert [i["id"] for i in first] == ["beads"]
    assert first[0]["label"] == "Beads v2"
    # snapshot returns a copy — mutating it must not affect the registry.
    first.append({"id": "ghost"})
    assert [i["id"] for i in reg.snapshot()] == ["beads"]
