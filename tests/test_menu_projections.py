"""The menu bar and the World panel are two projections of one menu model.

The two surfaces must show the same menus and route a click identically. They
did not: the World panel built its own short list of the display's own menus, so
a session's callback entry (lux's Beads, voxd's Music) reached the bar and never
the panel. These tests hold both surfaces to one model, so a menu that reaches
one and not the other fails here rather than in front of the user.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from punt_lux.display.menus import MenuBar, MenuModel, MenuSurface, WorldPanel
from punt_lux.display.replica.frame_visibility import FrameVisibility
from punt_lux.protocol import RemoteEventHandlerInvocation

from .menu_doubles import (
    SEPARATOR,
    FakeImGui,
    FakeTheme,
    Vec2,
    make_frame,
    make_menu_replica,
    wire_menu,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest

    from punt_lux.display.replica.menu_replica import MenuReplica

    from .menu_doubles import MenuLine

# One client — voxd, the machine-wide daemon — under the Clients menu, as the
# Hub replicates it: its own command, a rule, and the Hub's Details command.
_VOXD_MENU = wire_menu(
    "Clients",
    [
        wire_menu(
            "voxd",
            [
                {"label": "Music", "id": "conn-7\x1fmusic"},
                {"label": SEPARATOR},
                {"label": "Details", "id": "conn-7\x1f\x1fdetails"},
            ],
        )
    ],
)
# Two clients under the one Clients menu, as the Hub composes them: each with
# its own command, a rule, and the Hub's Details command at the foot.
_CLIENTS_MENU = wire_menu(
    "Clients",
    [
        wire_menu(
            "lux",
            [
                {"label": "Beads", "id": "conn-1\x1fbeads"},
                {"label": SEPARATOR},
                {"label": "Details", "id": "conn-1\x1f\x1fdetails"},
            ],
        ),
        wire_menu(
            "quarry",
            [
                {"label": "Beads", "id": "conn-2\x1fbeads"},
                {"label": SEPARATOR},
                {"label": "Details", "id": "conn-2\x1f\x1fdetails"},
            ],
        ),
    ],
)
# One agent bar, as ``set_menu`` replicates it.
_AGENT_MENU = wire_menu(
    "File", [{"label": "Open", "id": "file.open"}, {"label": SEPARATOR}]
)
# A menu no surface can decode: ``items`` is not something to iterate over.
_UNDECODABLE_MENU: dict[str, Any] = {"label": "voxd", "items": 7}


def _gone_away(_invocation: RemoteEventHandlerInvocation) -> None:
    """Fail the way a click's action fails when the Hub is no longer there."""
    msg = "the connection to the Hub is gone"
    raise RuntimeError(msg)


def _menus_drawn(fake: FakeImGui) -> tuple[MenuLine, ...]:
    """Return the menu lines a surface drew, without the panel's own chrome.

    The World panel draws a rule under its pin button. That rule belongs to the
    panel's frame, not to any menu, and the bar has nothing answering to it.
    """
    return tuple(
        line for line in fake.lines if line.path != () or line.label != SEPARATOR
    )


def _sections_drawn(fake: FakeImGui) -> tuple[str, ...]:
    """Return the top-level menu titles a surface drew, in order."""
    return tuple(line.label for line in _menus_drawn(fake) if line.path == ())


def _draw_bar(manager: MenuReplica, clicks: tuple[str, ...] = ()) -> FakeImGui:
    """Draw the menu bar and return what it drew."""
    imgui = FakeImGui(clicks)
    manager.render_bar(imgui)
    return imgui


def _draw_panel(manager: MenuReplica, clicks: tuple[str, ...] = ()) -> FakeImGui:
    """Open the World panel with a background click and return what it drew."""
    imgui = FakeImGui(clicks)
    imgui.click_background()
    manager.check_world_menu_background_click(imgui)
    manager.render_world_panel(imgui)
    return imgui


def _counting_themes(composed: list[str]) -> Callable[[], list[FakeTheme]]:
    """Return a theme supplier that records one entry per menu composition.

    Composing the menu asks the display for its themes exactly once, so the
    length of *composed* is the number of times the menu was built.
    """

    def themes() -> list[FakeTheme]:
        composed.append("composed")
        return []

    return themes


class TestOneMenuTwoSurfaces:
    """Whatever the model holds, both surfaces show."""

    def test_the_two_surfaces_draw_the_same_menu(self) -> None:
        manager = make_menu_replica(get_themes=lambda: [FakeTheme("imgui_colors_dark")])
        manager.replace_agent_menus([_AGENT_MENU])
        manager.replace_callback_menus([_VOXD_MENU])

        assert _menus_drawn(_draw_bar(manager)) == _menus_drawn(_draw_panel(manager))

    def test_a_client_callback_reaches_the_world_panel(self) -> None:
        manager = make_menu_replica()
        manager.replace_callback_menus([_VOXD_MENU])

        for imgui in (_draw_bar(manager), _draw_panel(manager)):
            assert "Clients" in imgui.labels_under()
            assert imgui.labels_under("Clients", "voxd")[0] == "Music"

    def test_an_agent_bar_reaches_both_surfaces(self) -> None:
        manager = make_menu_replica()
        manager.replace_agent_menus([_AGENT_MENU])

        for imgui in (_draw_bar(manager), _draw_panel(manager)):
            assert "File" in imgui.labels_under()
            assert imgui.labels_under("File") == ("Open", SEPARATOR)

    def test_a_swept_client_leaves_both_surfaces(self) -> None:
        manager = make_menu_replica()
        manager.replace_callback_menus([_VOXD_MENU])
        assert "voxd" in _draw_bar(manager).labels_under("Clients")

        # The lease lapsed; the Hub re-sent the menu without that client.
        manager.replace_callback_menus([])

        for imgui in (_draw_bar(manager), _draw_panel(manager)):
            assert "Clients" not in imgui.labels_under()

    def test_both_surfaces_draw_every_section_of_the_model(self) -> None:
        manager = make_menu_replica()
        manager.replace_agent_menus([_AGENT_MENU])
        manager.replace_callback_menus([_VOXD_MENU])
        expected = tuple(s.label for s in manager.menu_model().sections)

        assert expected == ("Lux", "Clients", "File", "Windows", "Help")
        for imgui in (_draw_bar(manager), _draw_panel(manager)):
            assert _sections_drawn(imgui) == expected

    def test_the_display_owns_menus_of_its_own_on_both_surfaces(self) -> None:
        manager = make_menu_replica(get_frames=lambda: {"f1": make_frame("f1")})

        for imgui in (_draw_bar(manager), _draw_panel(manager)):
            assert imgui.labels_under("Lux", "Settings") == (
                "Theme",
                SEPARATOR,
                "Always on Top",
                "Borderless",
                SEPARATOR,
                "Opacity",
            )
            assert imgui.line("Fit All").enabled
            assert imgui.line("Quit").shortcut == "Cmd+Q"


class TestTheClientsMenu:
    """Clients ▸ client ▸ command reaches both surfaces, nesting and all."""

    def test_both_surfaces_nest_the_clients_the_hub_composed(self) -> None:
        manager = make_menu_replica()
        manager.replace_callback_menus([_CLIENTS_MENU])

        for imgui in (_draw_bar(manager), _draw_panel(manager)):
            assert "Clients" in imgui.labels_under()
            assert imgui.labels_under("Clients") == ("lux", "quarry")
            assert imgui.labels_under("Clients", "lux") == (
                "Beads",
                SEPARATOR,
                "Details",
            )
            assert imgui.labels_under("Clients", "quarry") == (
                "Beads",
                SEPARATOR,
                "Details",
            )

    def test_the_two_surfaces_draw_the_nested_menu_identically(self) -> None:
        manager = make_menu_replica()
        manager.replace_callback_menus([_CLIENTS_MENU])

        assert _menus_drawn(_draw_bar(manager)) == _menus_drawn(_draw_panel(manager))

    def test_the_clients_menu_is_one_section_beside_the_displays_own(self) -> None:
        manager = make_menu_replica()
        manager.replace_callback_menus([_CLIENTS_MENU])

        for imgui in (_draw_bar(manager), _draw_panel(manager)):
            assert _sections_drawn(imgui) == ("Lux", "Clients", "Windows", "Help")

    def test_a_nested_leaf_click_routes_the_same_from_either_surface(self) -> None:
        sent: list[RemoteEventHandlerInvocation] = []
        manager = make_menu_replica(emit_event=sent.append)
        manager.replace_callback_menus(
            [
                wire_menu(
                    "Clients", [wire_menu("lux", [{"label": "Beads", "id": "c\x1fb"}])]
                )
            ]
        )

        _draw_bar(manager, clicks=("Beads",))
        _draw_panel(manager, clicks=("Beads",))

        assert len(sent) == 2
        from_bar, from_panel = sent
        assert from_bar.element_id == from_panel.element_id == "c\x1fb"
        assert from_bar.value == from_panel.value
        # The click is attributed to the client that owns the entry, not to the
        # menu the clients are gathered under.
        assert from_bar.value == {"menu": "lux", "item": "Beads"}

    def test_a_client_that_left_takes_its_submenu_off_both_surfaces(self) -> None:
        manager = make_menu_replica()
        manager.replace_callback_menus([_CLIENTS_MENU])
        assert "quarry" in _draw_bar(manager).labels_under("Clients")

        # One lease lapsed; the Hub re-sent the menu without that client.
        manager.replace_callback_menus(
            [
                wire_menu(
                    "Clients", [wire_menu("lux", [{"label": "Beads", "id": "c\x1fb"}])]
                )
            ]
        )

        for imgui in (_draw_bar(manager), _draw_panel(manager)):
            assert imgui.labels_under("Clients") == ("lux",)

    def test_the_last_client_leaving_takes_the_clients_menu_with_it(self) -> None:
        manager = make_menu_replica()
        manager.replace_callback_menus([_CLIENTS_MENU])

        manager.replace_callback_menus([])  # every lease lapsed

        for imgui in (_draw_bar(manager), _draw_panel(manager)):
            assert "Clients" not in imgui.labels_under()


class TestClickRouting:
    """A leaf sends the same invocation whichever surface was clicked."""

    def test_a_leaf_click_routes_the_same_from_either_surface(self) -> None:
        sent: list[RemoteEventHandlerInvocation] = []
        manager = make_menu_replica(emit_event=sent.append)
        manager.replace_callback_menus([_VOXD_MENU])

        _draw_bar(manager, clicks=("Music",))
        _draw_panel(manager, clicks=("Music",))

        assert len(sent) == 2
        from_bar, from_panel = sent
        assert from_bar.element_id == from_panel.element_id == "conn-7\x1fmusic"
        assert from_bar.action == from_panel.action == "menu"
        assert from_bar.value == from_panel.value
        assert from_bar.value == {"menu": "voxd", "item": "Music"}

    def test_an_untouched_menu_sends_nothing(self) -> None:
        sent: list[RemoteEventHandlerInvocation] = []
        manager = make_menu_replica(emit_event=sent.append)
        manager.replace_callback_menus([_VOXD_MENU])

        _draw_bar(manager)
        _draw_panel(manager)

        assert sent == []

    def test_an_item_without_a_routable_id_is_never_drawn_to_click(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        sent: list[RemoteEventHandlerInvocation] = []
        manager = make_menu_replica(emit_event=sent.append)

        with caplog.at_level(logging.ERROR):
            manager.replace_agent_menus(
                [wire_menu("File", [{"label": "Open", "id": 7}])]
            )

        imgui = _draw_bar(manager, clicks=("Open",))

        # A line that cannot route a click is not drawn as one to click: the
        # menu carrying it was rejected where it arrived.
        assert "File" not in imgui.labels_under()
        assert sent == []
        assert "agent_menus.0.items.0.id" in caplog.text


class TestAMenuThatCannotBeDrawn:
    """A malformed menu is rejected where it arrives, and costs only itself."""

    def test_a_malformed_menu_reaches_neither_surface(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        manager = make_menu_replica()

        with caplog.at_level(logging.ERROR):
            manager.replace_callback_menus([_UNDECODABLE_MENU])
            _draw_bar(manager)
            _draw_panel(manager)

        assert "callback_menus.0.items" in caplog.text
        # Rejected at the boundary, so no surface ever tries to draw it.
        assert caplog.text.count("Error rendering menus") == 0
        for imgui in (_draw_bar(manager), _draw_panel(manager)):
            assert "voxd" not in imgui.labels_under()

    def test_a_malformed_menu_costs_only_itself(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        manager = make_menu_replica()

        with caplog.at_level(logging.ERROR):
            manager.replace_callback_menus([_UNDECODABLE_MENU, _VOXD_MENU])
            manager.replace_agent_menus([_AGENT_MENU])

        for imgui in (_draw_bar(manager), _draw_panel(manager)):
            drawn = _sections_drawn(imgui)
            assert drawn == ("Lux", "Clients", "File", "Windows", "Help")
            assert imgui.labels_under("Clients", "voxd")[0] == "Music"

    def test_a_failing_action_still_closes_the_panels_window(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        manager = make_menu_replica(emit_event=_gone_away)
        manager.replace_callback_menus([_VOXD_MENU])

        with caplog.at_level(logging.ERROR):
            imgui = _draw_panel(manager, clicks=("Music",))

        assert imgui.windows == ("World",)
        assert imgui.open_windows == 0  # the panel ended its window on the way out
        assert "Error rendering menus" in caplog.text


class TestProjectionStructure:
    """Both surfaces render whatever composer they are handed."""

    def test_both_surfaces_are_menu_surfaces(self) -> None:
        assert isinstance(MenuBar(), MenuSurface)
        assert isinstance(WorldPanel(dict), MenuSurface)

    def test_a_projection_renders_the_model_it_is_given(self) -> None:
        manager = make_menu_replica()
        manager.replace_callback_menus([_VOXD_MENU])
        model = manager.menu_model()
        bar_imgui, panel_imgui = FakeImGui(), FakeImGui()
        panel = WorldPanel(dict)
        panel_imgui.click_background()
        panel.check_background_click(panel_imgui)

        MenuBar().render(bar_imgui, lambda: model)
        panel.render(panel_imgui, lambda: model)

        assert _menus_drawn(bar_imgui) == _menus_drawn(panel_imgui)

    def test_a_shut_surface_never_asks_for_a_model(self) -> None:
        asked: list[str] = []

        def compose() -> MenuModel:
            asked.append("asked")
            return MenuModel([])

        WorldPanel(dict).render(FakeImGui(), compose)  # never opened

        assert asked == []


class TestWorldPanelOpening:
    """The panel answers a click on the background and nothing else."""

    def test_the_panel_stays_shut_until_a_background_click(self) -> None:
        manager = make_menu_replica()
        imgui = FakeImGui()

        manager.render_world_panel(imgui)

        assert not manager.world_menu_open
        assert imgui.lines == ()
        assert imgui.windows == ()

    def test_a_shut_panel_composes_no_menu(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        composed: list[str] = []
        manager = make_menu_replica(get_themes=_counting_themes(composed))
        manager.replace_callback_menus([_VOXD_MENU])
        imgui = FakeImGui()  # no background click: the panel stays shut

        with caplog.at_level(logging.ERROR):
            manager.render_world_panel(imgui)

        assert composed == []  # nothing to draw, so nothing to decode
        assert caplog.text == ""

    def test_an_open_panel_composes_the_menu_once(self) -> None:
        composed: list[str] = []
        manager = make_menu_replica(get_themes=_counting_themes(composed))
        imgui = FakeImGui()
        imgui.click_background()
        manager.check_world_menu_background_click(imgui)

        manager.render_world_panel(imgui)

        assert composed == ["composed"]

    def test_a_background_click_opens_the_panel(self) -> None:
        manager = make_menu_replica()
        imgui = FakeImGui()
        imgui.click_background()

        manager.check_world_menu_background_click(imgui)
        manager.render_world_panel(imgui)

        assert manager.world_menu_open
        assert imgui.windows == ("World",)

    def test_a_click_on_a_widget_leaves_the_panel_shut(self) -> None:
        manager = make_menu_replica()
        imgui = FakeImGui()
        imgui.click_widget()

        manager.check_world_menu_background_click(imgui)

        assert not manager.world_menu_open

    def test_a_second_background_click_closes_the_panel(self) -> None:
        manager = make_menu_replica()
        imgui = FakeImGui()
        imgui.click_background()
        manager.check_world_menu_background_click(imgui)

        imgui.click_background()  # the user clicks the background again
        manager.check_world_menu_background_click(imgui)

        assert not manager.world_menu_open

    def test_a_click_over_the_dock_bar_leaves_the_panel_shut(self) -> None:
        manager = make_menu_replica(
            get_frames=lambda: {
                "f1": make_frame("f1", visibility=FrameVisibility.DOCKED)
            }
        )
        imgui = FakeImGui()
        imgui.click_background(Vec2(400.0, 790.0))  # inside the dock bar's strip

        manager.check_world_menu_background_click(imgui)

        assert not manager.world_menu_open

    def test_the_close_button_shuts_the_panel_and_ends_its_window(self) -> None:
        manager = make_menu_replica()
        opened = FakeImGui()
        opened.click_background()
        manager.check_world_menu_background_click(opened)
        manager.render_world_panel(opened)

        dismissed = FakeImGui()  # the next frame, with the user on the close button
        dismissed.click_close_button()
        manager.render_world_panel(dismissed)

        assert not manager.world_menu_open
        assert dismissed.open_windows == 0
        assert dismissed.lines == ()  # a dismissed panel draws no menus

    def test_clicking_a_menu_item_closes_the_unpinned_panel(self) -> None:
        manager = make_menu_replica()
        manager.replace_callback_menus([_VOXD_MENU])

        _draw_panel(manager, clicks=("Music",))

        assert not manager.world_menu_open
