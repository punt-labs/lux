"""ImGuiWindowRenderer opens a movable window with no close affordance.

The adapter under test is real; only the ImGui backend is faked at the render
boundary. The load-bearing assertion is that ``imgui.begin`` is called with NO
``p_open`` — a window element has no close button, so ImGui draws none and the
window cannot be dismissed. Placement is seeded ``first_use_ever`` and the flag
mask is folded from the window's enabled flags.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from punt_lux.display.render_loop import RenderLoop
from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
from punt_lux.display.renderers.imgui.window import ImGuiWindowRenderer
from punt_lux.protocol.elements.window import WindowElement
from punt_lux.protocol.elements.window_chrome import WindowFlags, WindowPlacement

if TYPE_CHECKING:
    import pytest


def _factory() -> ImGuiRendererFactory:
    raw_dir = tempfile.mkdtemp(prefix="lux-")
    server = RenderLoop(socket_path=str(Path(raw_dir) / "display.sock"))
    factory = server._imgui_renderer_factory
    assert isinstance(factory, ImGuiRendererFactory)
    return factory


def _patch(monkeypatch: pytest.MonkeyPatch, imgui: MagicMock) -> None:
    monkeypatch.setattr("punt_lux.display.renderers.imgui.window.imgui", imgui)


def test_begin_opens_window_without_p_open(monkeypatch: pytest.MonkeyPatch) -> None:
    imgui = MagicMock()
    imgui.begin.return_value = (True, True)
    _patch(monkeypatch, imgui)
    window = WindowElement(id="w", title="Panel")

    visible = ImGuiWindowRenderer(window, _factory()).begin()

    assert visible is True
    # The one call that proves no close affordance: begin receives only the
    # title id and a flags keyword — no p_open positional/second argument.
    (title_arg,), kwargs = imgui.begin.call_args
    assert title_arg == "Panel###w"
    assert set(kwargs) == {"flags"}


def test_begin_seeds_placement_first_use_ever(monkeypatch: pytest.MonkeyPatch) -> None:
    imgui = MagicMock()
    imgui.begin.return_value = (True, True)
    imgui.Cond_.first_use_ever.value = 4
    _patch(monkeypatch, imgui)
    window = WindowElement(
        id="w", placement=WindowPlacement(x=10, y=20, width=400, height=300)
    )

    ImGuiWindowRenderer(window, _factory()).begin()

    imgui.set_next_window_pos.assert_called_once_with((10, 20), 4)
    imgui.set_next_window_size.assert_called_once_with((400, 300), 4)


def test_flag_mask_folds_enabled_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    imgui = MagicMock()
    imgui.begin.return_value = (True, True)
    imgui.WindowFlags_.no_move.value = 1
    imgui.WindowFlags_.always_auto_resize.value = 64
    _patch(monkeypatch, imgui)
    window = WindowElement(id="w", flags=WindowFlags(no_move=True, auto_resize=True))

    ImGuiWindowRenderer(window, _factory()).begin()

    _args, kwargs = imgui.begin.call_args
    assert kwargs["flags"] == 1 | 64


def test_end_closes_the_window(monkeypatch: pytest.MonkeyPatch) -> None:
    imgui = MagicMock()
    imgui.begin.return_value = (False, True)
    _patch(monkeypatch, imgui)
    window = WindowElement(id="w", title="Panel")

    renderer = ImGuiWindowRenderer(window, _factory())
    expanded = renderer.begin()
    renderer.end(opened=expanded)

    # imgui.begin is always paired with imgui.end, even when collapsed.
    imgui.end.assert_called_once_with()


def test_title_change_keeps_window_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """A title change keeps the same ImGui window identity (the part after ###).

    The identity is the element id alone, so ImGui treats a renamed window as the
    same window — the user's drag/resize survives rather than the window snapping
    back to its first-use-ever placement. Under the old ``##`` identity the two
    labels would hash to different windows.
    """
    imgui = MagicMock()
    imgui.begin.return_value = (True, True)
    _patch(monkeypatch, imgui)
    factory = _factory()

    window = WindowElement(id="w", title="Panel")
    ImGuiWindowRenderer(window, factory).begin()
    first = imgui.begin.call_args[0][0]

    window.apply_patch({"title": "Renamed"})
    ImGuiWindowRenderer(window, factory).begin()
    second = imgui.begin.call_args[0][0]

    assert first == "Panel###w"
    assert second == "Renamed###w"
    # Different labels, identical ImGui identity (the part after ###).
    assert first.split("###", 1)[1] == second.split("###", 1)[1] == "w"
