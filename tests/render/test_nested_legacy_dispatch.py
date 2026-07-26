"""Nested-in-legacy ABC leaves paint through the unified factory route.

During the fork's mixed period a legacy container (group, window, ...) recurses
its children through ``ElementRenderer.render_element``. A migrated ABC leaf
nested there resolves the *same* adapter the top-level ABC path uses — the
factory's ``handles`` predicate routes it, so the leaf paints byte-identically
and never hits the ``[unsupported element: ...]`` fallback (DES-042).

These tests assert the routing decision GL-free: ``handles`` is True for the
migrated kinds and the factory returns the matching adapter; ``render_element``
sends handled elements through ``_render_via_factory`` (whose adapter applies its
own tooltip) and legacy elements through the string dispatch (with the shared
tooltip). Driving the real adapter paint would call into ImGui, which segfaults
without a GL context.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from punt_lux.display.element_renderer import ElementRenderer
from punt_lux.display.geometry_capture import GeometryCapture
from punt_lux.display.renderers.imgui.button import ImGuiButtonRenderer
from punt_lux.display.renderers.imgui.checkbox import ImGuiCheckboxRenderer
from punt_lux.display.renderers.imgui.dialog import ImGuiDialogRenderer
from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
from punt_lux.display.renderers.imgui.text import ImGuiTextRenderer
from punt_lux.display.table_renderer import TableRenderer
from punt_lux.display.texture_cache import TextureCache
from punt_lux.protocol.elements.button import ButtonElement
from punt_lux.protocol.elements.checkbox import CheckboxElement
from punt_lux.protocol.elements.dialog import DialogElement
from punt_lux.protocol.elements.layout import LegacyGroupElement, LegacyWindowElement
from punt_lux.protocol.elements.table import TableElement
from punt_lux.protocol.elements.text import TextElement
from punt_lux.protocol.messages.remote_invocation import RemoteEventHandlerInvocation
from punt_lux.scene.widget_state import WidgetState

if TYPE_CHECKING:
    from collections.abc import Generator

    import pytest


def _no_emit(_msg: object) -> None:
    """No-op Display-tier emit."""


def _no_emit_event(_msg: RemoteEventHandlerInvocation) -> None:
    """No-op interaction emit."""


def _no_check_dirty(_window_id: str) -> bool:
    return False


def _renderer() -> ElementRenderer:
    """Build an ElementRenderer wired to a real, GL-free ImGuiRendererFactory."""
    widget_state = WidgetState()
    textures = TextureCache()
    er = ElementRenderer(
        widget_state=widget_state,
        table_renderer=TableRenderer(
            widget_state=widget_state, emit_event=_no_emit_event
        ),
        emit_event=_no_emit_event,
        check_dirty_window=_no_check_dirty,
    )
    er.imgui_renderer_factory = ImGuiRendererFactory(
        widget_state=widget_state,
        texture_cache=textures,
        emit=_no_emit,
    )
    return er


def test_group_leaves_route_through_the_factory_adapter() -> None:
    er = _renderer()
    text = TextElement(id="t", content="hi")
    button = ButtonElement(id="b", label="Go")
    checkbox = CheckboxElement(id="c", label="On")
    group = LegacyGroupElement(id="g", children=[text, button, checkbox])
    factory = er.imgui_renderer_factory

    for child in group.children:
        # handles() True == routed to an adapter, NOT the unsupported fallback.
        assert factory.handles(child) is True
    assert isinstance(factory(text), ImGuiTextRenderer)
    assert isinstance(factory(button), ImGuiButtonRenderer)
    assert isinstance(factory(checkbox), ImGuiCheckboxRenderer)


def test_window_leaf_routes_through_the_factory_adapter() -> None:
    er = _renderer()
    button = ButtonElement(id="wb", label="Go")
    window = LegacyWindowElement(id="w", children=[button])
    factory = er.imgui_renderer_factory

    child = window.children[0]
    assert factory.handles(child) is True
    assert isinstance(factory(child), ImGuiButtonRenderer)


def test_dialog_routes_through_the_factory_adapter() -> None:
    # A dialog nested in a legacy container is factory-handled, resolving the
    # ImGuiDialogRenderer — never the [unsupported element: ...] fallback.
    er = _renderer()
    dialog = DialogElement(id="d1", title="Confirm")
    factory = er.imgui_renderer_factory
    assert factory.handles(dialog) is True
    assert isinstance(factory(dialog), ImGuiDialogRenderer)


def test_render_element_sends_handled_kinds_via_factory_without_generic_tooltip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A factory-handled element paints via _render_via_factory, whose adapter
    # applies its own tooltip; render_element must NOT run the generic pass too.
    er = _renderer()
    via_factory, tooltip = MagicMock(), MagicMock()
    monkeypatch.setattr(er, "_render_via_factory", via_factory)
    monkeypatch.setattr(er.imgui_renderer_factory, "apply_tooltip", tooltip)

    text = TextElement(id="t", content="hi", tooltip="hint")
    er.render_element(text)

    via_factory.assert_called_once_with(text)
    tooltip.assert_not_called()


def test_render_element_runs_generic_tooltip_for_legacy_kinds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Contrast: a legacy element takes the string dispatch and DOES get the
    # shared tooltip pass afterward — now the factory-owned painter.
    er = _renderer()
    render_group, tooltip = MagicMock(), MagicMock()
    monkeypatch.setattr(er, "_render_group", render_group)
    monkeypatch.setattr(er.imgui_renderer_factory, "apply_tooltip", tooltip)

    group = LegacyGroupElement(id="g", children=[])
    er.render_element(group)

    render_group.assert_called_once_with(group)
    tooltip.assert_called_once_with(group)


def _spy_measuring(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Replace GeometryCapture.measuring with a recorder that skips ImGui.

    The real ``measuring`` opens an ImGui group (a GL call that segfaults
    headless); the spy records the (id, kind) it was entered with instead, so a
    legacy leaf's capture wiring is provable GL-free. ``monkeypatch`` restores the
    real method at teardown.
    """
    entered: list[tuple[str, str]] = []

    @contextmanager
    def spy(_self: GeometryCapture, element_id: str, kind: str) -> Generator[None]:
        entered.append((element_id, kind))
        yield

    monkeypatch.setattr(GeometryCapture, "measuring", spy)
    return entered


def test_legacy_leaf_records_geometry_through_measuring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A legacy leaf (table) records its rect via the same measuring group the ABC
    # leaf template uses, so a visibly painted table is IN the geometry map, not
    # absent (which the contract reads as "did not paint").
    er = _renderer()
    monkeypatch.setattr(er, "_render_table", MagicMock())
    monkeypatch.setattr(er.imgui_renderer_factory, "apply_tooltip", MagicMock())
    entered = _spy_measuring(monkeypatch)

    er.render_element(TableElement(id="tbl"))

    assert entered == [("tbl", "table")]


def test_legacy_container_records_no_geometry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A legacy container records nothing itself — its children record as they
    # recurse — so measuring is never entered for the container.
    er = _renderer()
    monkeypatch.setattr(er, "_render_group", MagicMock())
    monkeypatch.setattr(er.imgui_renderer_factory, "apply_tooltip", MagicMock())
    entered = _spy_measuring(monkeypatch)

    er.render_element(LegacyGroupElement(id="g", children=[]))

    assert entered == []
