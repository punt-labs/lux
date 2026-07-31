"""The menu bar and the World panel are two projections of one menu model.

The two surfaces must show the same menus and route a click identically. They
did not: the World panel built its own short list of the display's own menus, so
a session's callback entry (lux's Beads, voxd's Music) reached the bar and never
the panel. These tests hold both surfaces to one model, so a menu that reaches
one and not the other fails here rather than in front of the user.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, get_type_hints

from punt_lux.display.menus import MenuBar, MenuModel, WorldPanel
from punt_lux.protocol import RemoteEventHandlerInvocation

from .menu_doubles import (
    SEPARATOR,
    FakeImGui,
    FakeTheme,
    Vec2,
    make_frame,
    make_menu_manager,
    wire_menu,
)

if TYPE_CHECKING:
    from punt_lux.display.menu_manager import MenuManager

    from .menu_doubles import MenuLine

# One session that registered one callback, as the Hub replicates it.
_VOXD_MENU = wire_menu("voxd — vox", [{"label": "Music", "id": "conn-7\x1fmusic"}])
# One agent bar, as ``set_menu`` replicates it.
_AGENT_MENU = wire_menu(
    "File", [{"label": "Open", "id": "file.open"}, {"label": SEPARATOR}]
)


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


def _draw_bar(manager: MenuManager, clicks: tuple[str, ...] = ()) -> FakeImGui:
    """Draw the menu bar and return what it drew."""
    imgui = FakeImGui(clicks)
    manager.render_bar(imgui)
    return imgui


def _draw_panel(manager: MenuManager, clicks: tuple[str, ...] = ()) -> FakeImGui:
    """Open the World panel with a background click and return what it drew."""
    imgui = FakeImGui(clicks)
    imgui.click_background()
    manager.check_world_menu_background_click(imgui)
    manager.render_world_panel(imgui)
    return imgui


class TestOneMenuTwoSurfaces:
    """Whatever the model holds, both surfaces show."""

    def test_the_two_surfaces_draw_the_same_menu(self) -> None:
        manager = make_menu_manager(get_themes=lambda: [FakeTheme("imgui_colors_dark")])
        manager.agent_menus = [_AGENT_MENU]
        manager.callback_menus = [_VOXD_MENU]

        assert _menus_drawn(_draw_bar(manager)) == _menus_drawn(_draw_panel(manager))

    def test_a_session_callback_reaches_the_world_panel(self) -> None:
        manager = make_menu_manager()
        manager.callback_menus = [_VOXD_MENU]

        for imgui in (_draw_bar(manager), _draw_panel(manager)):
            assert "voxd — vox" in imgui.labels_under()
            assert imgui.labels_under("voxd — vox") == ("Music",)

    def test_an_agent_bar_reaches_both_surfaces(self) -> None:
        manager = make_menu_manager()
        manager.agent_menus = [_AGENT_MENU]

        for imgui in (_draw_bar(manager), _draw_panel(manager)):
            assert "File" in imgui.labels_under()
            assert imgui.labels_under("File") == ("Open", SEPARATOR)

    def test_a_swept_session_leaves_both_surfaces(self) -> None:
        manager = make_menu_manager()
        manager.callback_menus = [_VOXD_MENU]
        assert "voxd — vox" in _draw_bar(manager).labels_under()

        manager.callback_menus = []  # the lease lapsed; the Hub re-sent without it

        for imgui in (_draw_bar(manager), _draw_panel(manager)):
            assert "voxd — vox" not in imgui.labels_under()

    def test_both_surfaces_draw_every_section_of_the_model(self) -> None:
        manager = make_menu_manager()
        manager.agent_menus = [_AGENT_MENU]
        manager.callback_menus = [_VOXD_MENU]
        expected = tuple(s.label for s in manager.menu_model().sections)

        assert expected == ("Lux", "Windows", "Help", "File", "voxd — vox")
        for imgui in (_draw_bar(manager), _draw_panel(manager)):
            assert _sections_drawn(imgui) == expected

    def test_the_display_owns_menus_of_its_own_on_both_surfaces(self) -> None:
        manager = make_menu_manager(get_frames=lambda: {"f1": make_frame("f1")})

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


class TestClickRouting:
    """A leaf sends the same invocation whichever surface was clicked."""

    def test_a_leaf_click_routes_the_same_from_either_surface(self) -> None:
        sent: list[RemoteEventHandlerInvocation] = []
        manager = make_menu_manager(emit_event=sent.append)
        manager.callback_menus = [_VOXD_MENU]

        _draw_bar(manager, clicks=("Music",))
        _draw_panel(manager, clicks=("Music",))

        assert len(sent) == 2
        from_bar, from_panel = sent
        assert from_bar.element_id == from_panel.element_id == "conn-7\x1fmusic"
        assert from_bar.action == from_panel.action == "menu"
        assert from_bar.value == from_panel.value
        assert from_bar.value == {"menu": "voxd — vox", "item": "Music"}

    def test_an_untouched_menu_sends_nothing(self) -> None:
        sent: list[RemoteEventHandlerInvocation] = []
        manager = make_menu_manager(emit_event=sent.append)
        manager.callback_menus = [_VOXD_MENU]

        _draw_bar(manager)
        _draw_panel(manager)

        assert sent == []

    def test_an_item_without_a_routable_id_sends_nothing(self) -> None:
        sent: list[RemoteEventHandlerInvocation] = []
        manager = make_menu_manager(emit_event=sent.append)
        manager.agent_menus = [wire_menu("File", [{"label": "Open", "id": 7}])]

        imgui = _draw_bar(manager, clicks=("Open",))

        assert imgui.labels_under("File") == ("Open",)
        assert sent == []


class TestProjectionStructure:
    """Both surfaces are typed to render a model they are handed."""

    def test_both_projections_take_the_menu_model(self) -> None:
        namespace = {"MenuModel": MenuModel}
        bar = get_type_hints(MenuBar.render, localns=namespace)
        panel = get_type_hints(WorldPanel.render, localns=namespace)

        assert bar["model"] is MenuModel
        assert panel["model"] is MenuModel

    def test_a_projection_renders_the_model_it_is_given(self) -> None:
        manager = make_menu_manager()
        manager.callback_menus = [_VOXD_MENU]
        model = manager.menu_model()
        bar_imgui, panel_imgui = FakeImGui(), FakeImGui()
        panel = WorldPanel(dict)
        panel_imgui.click_background()
        panel.check_background_click(panel_imgui)

        MenuBar().render(bar_imgui, model)
        panel.render(panel_imgui, model)

        assert _menus_drawn(bar_imgui) == _menus_drawn(panel_imgui)


class TestWorldPanelOpening:
    """The panel answers a click on the background and nothing else."""

    def test_the_panel_stays_shut_until_a_background_click(self) -> None:
        manager = make_menu_manager()
        imgui = FakeImGui()

        manager.render_world_panel(imgui)

        assert not manager.world_menu_open
        assert imgui.lines == ()
        assert imgui.windows == ()

    def test_a_background_click_opens_the_panel(self) -> None:
        manager = make_menu_manager()
        imgui = FakeImGui()
        imgui.click_background()

        manager.check_world_menu_background_click(imgui)
        manager.render_world_panel(imgui)

        assert manager.world_menu_open
        assert imgui.windows == ("World",)

    def test_a_click_on_a_widget_leaves_the_panel_shut(self) -> None:
        manager = make_menu_manager()
        imgui = FakeImGui()
        imgui.click_widget()

        manager.check_world_menu_background_click(imgui)

        assert not manager.world_menu_open

    def test_a_second_background_click_closes_the_panel(self) -> None:
        manager = make_menu_manager()
        imgui = FakeImGui()
        imgui.click_background()
        manager.check_world_menu_background_click(imgui)

        manager.check_world_menu_background_click(imgui)

        assert not manager.world_menu_open

    def test_a_click_over_the_dock_bar_leaves_the_panel_shut(self) -> None:
        manager = make_menu_manager(
            get_frames=lambda: {"f1": make_frame("f1", minimized=True)}
        )
        imgui = FakeImGui()
        imgui.click_background(Vec2(400.0, 790.0))  # inside the dock bar's strip

        manager.check_world_menu_background_click(imgui)

        assert not manager.world_menu_open

    def test_clicking_a_menu_item_closes_the_unpinned_panel(self) -> None:
        manager = make_menu_manager()
        manager.callback_menus = [_VOXD_MENU]

        _draw_panel(manager, clicks=("Music",))

        assert not manager.world_menu_open
