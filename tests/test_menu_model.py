"""The menu model: entries that render themselves and menus built from the wire."""

from __future__ import annotations

from punt_lux.display.menus import MenuItem, MenuModel, MenuSeparator, Submenu
from punt_lux.protocol import RemoteEventHandlerInvocation

from .menu_doubles import SEPARATOR, FakeImGui, checked_menu, ignore, wire_menu


def _nothing() -> None:
    """Stand in for an action under test that should not matter."""


class TestMenuItem:
    """One line in a menu carries its own label, state, and action."""

    def test_a_click_runs_the_action(self) -> None:
        ran: list[str] = []
        item = MenuItem("Open", lambda: ran.append("open"))

        assert item.render(FakeImGui(("Open",))) is True
        assert ran == ["open"]

    def test_no_click_leaves_the_action_alone(self) -> None:
        ran: list[str] = []
        item = MenuItem("Open", lambda: ran.append("open"))

        assert item.render(FakeImGui()) is False
        assert ran == []

    def test_an_item_carries_its_shortcut_and_enabled_state(self) -> None:
        imgui = FakeImGui()

        MenuItem("Quit", _nothing, shortcut="Cmd+Q", enabled=False).render(imgui)

        drawn = imgui.line("Quit")
        assert drawn.shortcut == "Cmd+Q"
        assert drawn.enabled is False

    def test_a_toggle_shows_its_checked_state(self) -> None:
        imgui = FakeImGui()

        MenuItem.toggle("Always on Top", _nothing, checked=True).render(imgui)

        assert imgui.line("Always on Top").checked is True

    def test_a_caption_is_disabled_and_cannot_be_clicked(self) -> None:
        imgui = FakeImGui(("Lux v9.9.9",))

        activated = MenuItem.caption("Lux v9.9.9").render(imgui)

        assert activated is False  # ImGui never activates a disabled item
        assert imgui.line("Lux v9.9.9").enabled is False

    def test_an_item_reports_the_label_it_shows(self) -> None:
        assert MenuItem("Open", _nothing).label == "Open"


class TestSubmenu:
    """A menu renders its entries while it is open, and nothing while it is shut."""

    def test_an_open_menu_renders_its_entries(self) -> None:
        imgui = FakeImGui()
        menu = Submenu("File", [MenuItem("Open", _nothing), MenuSeparator()])

        assert menu.render(imgui) is False
        assert imgui.labels_under("File") == ("Open", SEPARATOR)

    def test_a_shut_menu_renders_no_entries(self) -> None:
        imgui = FakeImGui(menus_open=False)

        Submenu("File", [MenuItem("Open", _nothing)]).render(imgui)

        assert imgui.labels_under("File") == ()

    def test_a_menu_reports_a_click_on_any_of_its_entries(self) -> None:
        menu = Submenu(
            "File", [MenuItem("Open", _nothing), MenuItem("Close", _nothing)]
        )

        assert menu.render(FakeImGui(("Close",))) is True

    def test_the_id_suffix_stays_out_of_the_visible_label(self) -> None:
        imgui = FakeImGui()

        Submenu("File", [MenuItem("Open", _nothing)]).render(imgui, "##world")

        assert imgui.labels_under() == ("File",)
        assert imgui.labels_under("File") == ("Open",)

    def test_a_menu_reports_its_label_and_entries(self) -> None:
        entries = (MenuItem("Open", _nothing),)
        menu = Submenu("File", entries)

        assert menu.label == "File"
        assert menu.entries == entries


class TestSubmenuFromWire:
    """A checked replicated menu becomes a menu that routes clicks to the Hub."""

    def test_items_become_entries_in_order(self) -> None:
        imgui = FakeImGui()
        menu = Submenu.from_wire(
            checked_menu(
                wire_menu(
                    "File",
                    [
                        {"label": "Open", "id": "file.open", "shortcut": "Cmd+O"},
                        {"label": SEPARATOR},
                        {"label": "Close", "id": "file.close", "enabled": False},
                    ],
                )
            ),
            ignore,
            ignore,
        )

        menu.render(imgui)

        assert imgui.labels_under("File") == ("Open", SEPARATOR, "Close")
        assert imgui.line("Open").shortcut == "Cmd+O"
        assert imgui.line("Close").enabled is False

    def test_a_click_emits_the_menu_invocation(self) -> None:
        sent: list[RemoteEventHandlerInvocation] = []
        menu = Submenu.from_wire(
            checked_menu(
                wire_menu("voxd", [{"label": "Music", "id": "conn\x1fmusic"}])
            ),
            sent.append,
            ignore,
        )

        menu.render(FakeImGui(("Music",)))

        assert len(sent) == 1
        assert sent[0].element_id == "conn\x1fmusic"
        assert sent[0].action == "menu"
        assert sent[0].value == {"menu": "voxd", "item": "Music"}

    def test_a_nested_menu_becomes_a_nested_menu(self) -> None:
        imgui = FakeImGui()
        menu = Submenu.from_wire(
            checked_menu(
                wire_menu(
                    "Clients",
                    [wire_menu("lux", [{"label": "Beads", "id": "c\x1fb"}])],
                )
            ),
            ignore,
            ignore,
        )

        menu.render(imgui)

        assert imgui.labels_under("Clients") == ("lux",)
        assert imgui.labels_under("Clients", "lux") == ("Beads",)

    def test_a_disabled_item_routes_nothing_when_clicked(self) -> None:
        sent: list[RemoteEventHandlerInvocation] = []
        menu = Submenu.from_wire(
            checked_menu(
                wire_menu(
                    "File", [{"label": "Close", "id": "file.close", "enabled": False}]
                )
            ),
            sent.append,
            ignore,
        )

        imgui = FakeImGui(("Close",))

        assert menu.render(imgui) is False
        assert imgui.line("Close").enabled is False
        assert sent == []

    def test_a_frame_owning_leaf_raises_locally_before_emitting(self) -> None:
        calls: list[str] = []
        menu = Submenu.from_wire(
            checked_menu(
                wire_menu(
                    "Clients",
                    [{"label": "Beads", "id": "c\x1fbeads", "frame_id": "beads-lux"}],
                )
            ),
            lambda _event: calls.append("emit"),
            lambda frame_id: calls.append(f"raise:{frame_id}"),
        )

        menu.render(FakeImGui(("Beads",)))

        assert calls == ["raise:beads-lux", "emit"]

    def test_a_leaf_with_no_frame_never_raises(self) -> None:
        raised: list[str] = []
        menu = Submenu.from_wire(
            checked_menu(
                wire_menu("Clients", [{"label": "Details", "id": "c\x1fdetails"}])
            ),
            ignore,
            raised.append,
        )

        menu.render(FakeImGui(("Details",)))

        assert raised == []

    def test_a_menu_without_items_renders_as_an_empty_menu(self) -> None:
        imgui = FakeImGui()

        Submenu.from_wire(checked_menu({"label": "File"}), ignore, ignore).render(imgui)

        assert imgui.labels_under() == ("File",)
        assert imgui.labels_under("File") == ()


class TestMenuModel:
    """The model renders every menu it holds, in order."""

    def test_sections_render_in_order(self) -> None:
        imgui = FakeImGui()
        model = MenuModel([Submenu("Lux", []), Submenu("Windows", [])])

        assert model.render(imgui) is False
        assert imgui.labels_under() == ("Lux", "Windows")
        assert tuple(s.label for s in model.sections) == ("Lux", "Windows")

    def test_a_click_in_any_section_is_reported(self) -> None:
        model = MenuModel(
            [
                Submenu("Lux", [MenuItem("Quit", _nothing)]),
                Submenu("Windows", [MenuItem("Clear All", _nothing)]),
            ]
        )

        assert model.render(FakeImGui(("Clear All",))) is True

    def test_every_section_renders_even_after_one_is_clicked(self) -> None:
        imgui = FakeImGui(("Quit",))
        model = MenuModel(
            [
                Submenu("Lux", [MenuItem("Quit", _nothing)]),
                Submenu("Windows", [MenuItem("Clear All", _nothing)]),
            ]
        )

        model.render(imgui)

        assert imgui.labels_under("Windows") == ("Clear All",)

    def test_shut_menus_are_drawn_as_siblings(self) -> None:
        imgui = FakeImGui(menus_open=False)

        MenuModel([Submenu("Lux", []), Submenu("Windows", [])]).render(imgui)

        assert imgui.labels_under() == ("Lux", "Windows")

    def test_an_empty_model_draws_nothing(self) -> None:
        imgui = FakeImGui()

        assert MenuModel([]).render(imgui) is False
        assert imgui.lines == ()
