"""MenuReplica — the menu state the Hub replicates and the model it composes.

The manager holds the agent bars and the Hub-composed Clients menu, and
composes them with the display's own menus into the one model both surfaces
render. Clicking an item here drives the real entry the bar would draw, so what
these tests exercise is what the user gets.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from punt_lux.display.menus import MenuModel
from tests.menu_doubles import (
    SEPARATOR,
    FakeChrome,
    FakeImGui,
    FakeTheme,
    make_frame,
    make_menu_replica as _manager,
    wire_menu,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from punt_lux.display.menus.wire import WireMenu


def _labels(menus: Sequence[WireMenu]) -> tuple[str, ...]:
    """Return the label of every menu held, in order."""
    return tuple(menu.label for menu in menus)


class TestReplicatedMenuState:
    """The Hub-sent menus the display holds until the next send replaces them."""

    def test_callback_menus_default_empty(self) -> None:
        assert _manager().callback_menus == ()

    def test_callback_menus_replace_the_whole_set(self) -> None:
        manager = _manager()

        manager.replace_callback_menus(
            [wire_menu("voxd", [{"label": "Music", "id": "v\x1fm"}])]
        )
        assert _labels(manager.callback_menus) == ("voxd",)

        manager.replace_callback_menus([])
        assert manager.callback_menus == ()

    def test_agent_menus_default_empty(self) -> None:
        assert _manager().agent_menus == ()

    def test_agent_menus_replace_the_whole_bar(self) -> None:
        manager = _manager()

        manager.replace_agent_menus(
            [wire_menu("File", [{"label": "Open", "id": "file.open"}])]
        )

        assert _labels(manager.agent_menus) == ("File",)
        assert [line.item_id for _path, line in manager.agent_menus[0].lines()] == [
            "file.open"
        ]


class TestMenuModelComposition:
    """The model interleaves the display's Lux section, callback menus (Clients),
    agent bars, and the display's chrome sections (Windows, Help) — in that order."""

    def test_the_display_has_menus_of_its_own_with_nothing_replicated(self) -> None:
        model = _manager().menu_model()

        assert isinstance(model, MenuModel)
        assert tuple(s.label for s in model.sections) == ("Lux", "Windows", "Help")

    def test_callback_and_agent_menus_slot_between_lux_and_chrome(self) -> None:
        manager = _manager()
        manager.replace_agent_menus([wire_menu("File", [])])
        manager.replace_callback_menus([wire_menu("voxd", [])])

        labels = tuple(s.label for s in manager.menu_model().sections)

        assert labels == ("Lux", "voxd", "File", "Windows", "Help")

    def test_the_model_is_rebuilt_from_live_state(self) -> None:
        opacity = 0.25
        manager = _manager(get_opacity=lambda: opacity)
        assert manager.menu_model() is not manager.menu_model()

        imgui = FakeImGui()
        manager.render_bar(imgui)

        assert imgui.line("25%").checked is True
        assert imgui.line("100%").checked is False

    def test_the_help_menu_names_the_running_version(self) -> None:
        from punt_lux import __version__

        imgui = FakeImGui()
        _manager().render_bar(imgui)

        assert imgui.labels_under("Help") == (f"Lux v{__version__}",)


class TestTheDisplaysOwnItems:
    """Each built-in item does what its label says when it is clicked."""

    def test_choosing_a_theme_applies_it(self) -> None:
        chosen: list[str] = []
        manager = _manager(
            get_themes=lambda: [FakeTheme("imgui_colors_light")],
            on_theme_selected=chosen.append,
        )

        manager.render_bar(FakeImGui(("Imgui Colors Light",)))

        assert chosen == ["imgui_colors_light"]

    def test_increasing_the_font_steps_up_and_stops_at_the_ceiling(self) -> None:
        scales: list[float] = []
        manager = _manager(
            get_font_scale=lambda: 1.1, on_font_scale_changed=scales.append
        )
        manager.render_bar(FakeImGui(("Increase Font",)))

        at_ceiling = _manager(
            get_font_scale=lambda: 3.0, on_font_scale_changed=scales.append
        )
        at_ceiling.render_bar(FakeImGui(("Increase Font",)))

        assert scales == [1.2, 3.0]

    def test_decreasing_the_font_steps_down_and_stops_at_the_floor(self) -> None:
        scales: list[float] = []
        manager = _manager(
            get_font_scale=lambda: 1.1, on_font_scale_changed=scales.append
        )
        manager.render_bar(FakeImGui(("Decrease Font",)))

        at_floor = _manager(
            get_font_scale=lambda: 0.5, on_font_scale_changed=scales.append
        )
        at_floor.render_bar(FakeImGui(("Decrease Font",)))

        assert scales == [1.0, 0.5]

    def test_choosing_an_opacity_applies_it(self) -> None:
        applied: list[float] = []
        manager = _manager(on_opacity_changed=applied.append)

        manager.render_bar(FakeImGui(("50%",)))

        assert applied == [0.5]

    def test_borderless_flips_the_window_decoration(self) -> None:
        decorated: list[bool] = []
        manager = _manager(
            get_decorated=lambda: True, on_decorated_toggled=decorated.append
        )

        imgui = FakeImGui(("Borderless",))
        manager.render_bar(imgui)

        assert decorated == [False]
        assert imgui.line("Borderless").checked is False

    def test_always_on_top_flips_the_window_state(self) -> None:
        chrome = FakeChrome(top_most=False)
        manager = _manager(chrome=chrome)

        imgui = FakeImGui(("Always on Top",))
        manager.render_bar(imgui)

        assert chrome.asked == ("set_top_most=True",)
        assert imgui.line("Always on Top").checked is False

    def test_quit_asks_the_window_to_close(self) -> None:
        chrome = FakeChrome()

        _manager(chrome=chrome).render_bar(FakeImGui(("Quit",)))

        assert chrome.asked == ("quit",)

    def test_reset_size_asks_the_window_to_resize(self) -> None:
        chrome = FakeChrome()

        _manager(chrome=chrome).render_bar(FakeImGui(("Reset Size",)))

        assert chrome.asked == ("reset_size",)

    def test_clear_all_and_fit_all_reach_the_display(self) -> None:
        done: list[str] = []
        manager = _manager(
            get_frames=lambda: {"f1": make_frame("f1")},
            on_clear_all=lambda: done.append("clear"),
            on_fit_all=lambda: done.append("fit"),
        )

        manager.render_bar(FakeImGui(("Clear All", "Fit All")))

        assert done == ["fit", "clear"]


class TestFrameItems:
    """Collapse and expand act on every frame, and go dim when they cannot."""

    def test_collapse_all_minimizes_every_frame(self) -> None:
        frames = {"a": make_frame("a"), "b": make_frame("b")}
        manager = _manager(get_frames=lambda: frames)

        manager.render_bar(FakeImGui(("Collapse All",)))

        assert all(frame.minimized for frame in frames.values())

    def test_expand_all_restores_every_frame(self) -> None:
        frames = {"a": make_frame("a", minimized=True)}
        manager = _manager(get_frames=lambda: frames)

        manager.render_bar(FakeImGui(("Expand All",)))

        assert not frames["a"].minimized

    def test_the_frame_items_are_dim_with_no_frames(self) -> None:
        imgui = FakeImGui()

        _manager().render_bar(imgui)

        assert imgui.line("Collapse All").enabled is False
        assert imgui.line("Expand All").enabled is False
        assert imgui.line("Fit All").enabled is False

    def test_expand_all_is_dim_while_every_frame_is_open(self) -> None:
        imgui = FakeImGui()

        _manager(get_frames=lambda: {"a": make_frame("a")}).render_bar(imgui)

        assert imgui.line("Collapse All").enabled is True
        assert imgui.line("Expand All").enabled is False

    def test_the_windows_menu_separates_frames_from_window_chrome(self) -> None:
        imgui = FakeImGui()

        _manager().render_bar(imgui)

        assert imgui.labels_under("Windows") == (
            "Collapse All",
            "Expand All",
            "Fit All",
            SEPARATOR,
            "Clear All",
            "Reset Size",
        )
