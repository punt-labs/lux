"""HubMenuRegistry — the Hub-owned agent menu bar, read fresh and copied out.

The registry holds the agent-defined bar the agent set. A read hands out deep
copies so a caller cannot reach back through a returned menu and mutate stored
state, and ``wire_snapshot`` renders the bar as the untyped payloads the display
consumes, composed under the registry's one lock at send time.
"""

from __future__ import annotations

from punt_lux.domain.hub.menu_models import Menu, MenuAction
from punt_lux.domain.hub.menu_registry import HubMenuRegistry


def test_set_menus_replaces_the_bar() -> None:
    reg = HubMenuRegistry()
    reg.set_menus([Menu(label="File", items=[MenuAction(id="open", label="Open")])])
    reg.set_menus([Menu(label="Edit", items=[MenuAction(id="undo", label="Undo")])])

    bar = reg.menu_bar()
    assert [menu.label for menu in bar] == ["Edit"]


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


def test_wire_snapshot_renders_the_bar_as_wire_payloads() -> None:
    reg = HubMenuRegistry()
    reg.set_menus(
        [
            Menu(label="File", items=[MenuAction(id="open", label="Open")]),
            Menu(label="Run", items=[MenuAction(id="go", label="Go", shortcut="F5")]),
        ]
    )

    wire = reg.wire_snapshot()
    assert [menu["label"] for menu in wire] == ["File", "Run"]
    run_items = wire[1]["items"]
    assert isinstance(run_items, list)
    assert run_items[0] == {"label": "Go", "id": "go", "shortcut": "F5"}


def test_wire_snapshot_of_an_empty_registry_is_empty() -> None:
    assert HubMenuRegistry().wire_snapshot() == ()
