"""ImGui per-kind adapters — factory dispatch, leaf paint, dialog dismiss.

Covers the render-path-unification adapters without a live GL context.
The paint methods that call into real ImGui (a dialog's ``begin``/``end``
popup chrome) segfault without a frame, so only the GL-free surface is unit
tested here; the live interaction loops are the leader-run e2e.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from punt_lux.display.element_renderer import ElementRenderer
from punt_lux.display.renderers.imgui import (
    button as button_module,
    checkbox as checkbox_module,
    collapsing_header as collapsing_header_module,
    group as group_module,
)
from punt_lux.display.renderers.imgui.button import ImGuiButtonRenderer
from punt_lux.display.renderers.imgui.checkbox import ImGuiCheckboxRenderer
from punt_lux.display.renderers.imgui.collapsing_header import (
    ImGuiCollapsingHeaderRenderer,
)
from punt_lux.display.renderers.imgui.dialog import ImGuiDialogRenderer
from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
from punt_lux.display.renderers.imgui.group import ImGuiGroupRenderer
from punt_lux.display.renderers.imgui.tab_bar import ImGuiTabBarRenderer
from punt_lux.display.renderers.imgui.text import ImGuiTextRenderer
from punt_lux.display.table_renderer import TableRenderer
from punt_lux.display.texture_cache import TextureCache
from punt_lux.protocol.elements.button import ButtonElement
from punt_lux.protocol.elements.checkbox import CheckboxElement
from punt_lux.protocol.elements.collapsing_header import CollapsingHeaderElement
from punt_lux.protocol.elements.dialog import DialogElement
from punt_lux.protocol.elements.group import GroupElement
from punt_lux.protocol.elements.tab_bar import TabBarElement
from punt_lux.protocol.elements.text import TextElement
from punt_lux.protocol.messages.remote_invocation import RemoteEventHandlerInvocation
from punt_lux.scene.widget_state import WidgetState

if TYPE_CHECKING:
    import pytest


def _no_emit(_msg: object) -> None:
    """No-op Display-tier emit."""


def _no_emit_event(_msg: RemoteEventHandlerInvocation) -> None:
    """No-op interaction emit."""


def _no_check_dirty(_window_id: str) -> bool:
    return False


def _element_renderer(widget_state: WidgetState) -> ElementRenderer:
    textures = TextureCache()
    return ElementRenderer(
        widget_state=widget_state,
        texture_cache=textures,
        table_renderer=TableRenderer(
            widget_state=widget_state, emit_event=_no_emit_event
        ),
        emit_event=_no_emit_event,
        check_dirty_window=_no_check_dirty,
    )


def _factory(widget_state: WidgetState | None = None) -> ImGuiRendererFactory:
    ws = widget_state or WidgetState()
    return ImGuiRendererFactory(
        widget_state=ws,
        texture_cache=TextureCache(),
        emit=_no_emit,
    )


# -- factory dispatch ------------------------------------------------------


def test_factory_dispatches_each_migrated_kind_to_its_adapter() -> None:
    factory = _factory()
    assert isinstance(factory(TextElement(id="t", content="x")), ImGuiTextRenderer)
    assert isinstance(factory(ButtonElement(id="b", label="Go")), ImGuiButtonRenderer)
    assert isinstance(
        factory(CheckboxElement(id="c", label="On")), ImGuiCheckboxRenderer
    )
    assert isinstance(factory(DialogElement(id="d", title="?")), ImGuiDialogRenderer)


def test_factory_raises_for_unmigrated_kind() -> None:
    import pytest

    with pytest.raises(ValueError, match="no imgui renderer"):
        _factory()(object())


def test_introspection_element_kind_total_is_25() -> None:
    # The four ABC kinds stay in the legacy dispatch tables during the fork's
    # mixed period, so the honest total is 25 with no factory addend.
    er = _element_renderer(WidgetState())
    assert er.element_kind_count == 25


# -- leaf adapters ---------------------------------------------------------


def test_button_adapter_paints_via_renderer_then_shared_tooltip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    render = MagicMock()
    monkeypatch.setattr(button_module, "ButtonRenderer", lambda: render)
    factory = MagicMock()
    elem = ButtonElement(id="b", label="Go")
    adapter = ImGuiButtonRenderer(elem, factory)

    assert adapter.begin() is True
    adapter.paint()
    adapter.end(opened=True)

    render.render.assert_called_once_with(elem)
    factory.apply_tooltip.assert_called_once_with(elem)


def test_checkbox_adapter_paints_via_renderer_then_shared_tooltip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    render = MagicMock()
    monkeypatch.setattr(checkbox_module, "CheckboxRenderer", lambda: render)
    factory = MagicMock()
    elem = CheckboxElement(id="c", label="On")
    adapter = ImGuiCheckboxRenderer(elem, factory)

    assert adapter.begin() is True
    adapter.paint()
    adapter.end(opened=True)

    render.render.assert_called_once_with(elem)
    factory.apply_tooltip.assert_called_once_with(elem)


# -- container adapters: the tooltip attaches to the container's own item ---
#
# Regression guard for the hover-item timing bug: the container adapters route
# through the factory, which returns before ``render_element``'s generic tooltip
# pass, so they must paint the tooltip themselves — but at the point where
# ImGui's ``is_item_hovered`` refers to the *container's own* chrome, not the
# last child. That point differs per container:
#   - collapsing_header: the header item lives in ``begin`` — tooltip attaches
#     there, before any child; painting it in ``end`` (after children) would
#     bind to the last child.
#   - group: ``begin_vertical``/``end_vertical`` act as one item whose bbox
#     registers only after the close — tooltip attaches in ``end`` after it.
#   - tab_bar: only per-tab items exist, no whole-bar item — so no tooltip is
#     painted (the field round-trips without a wrong-item target).


def test_collapsing_header_adapter_applies_tooltip_in_begin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The header item is submitted in begin(); the tooltip must attach there.
    fake_imgui = MagicMock()
    fake_imgui.collapsing_header.return_value = False  # collapsed: no toggle fire
    monkeypatch.setattr(collapsing_header_module, "imgui", fake_imgui)
    factory = MagicMock()
    elem = CollapsingHeaderElement(id="c", label="Section", tooltip="hint")
    adapter = ImGuiCollapsingHeaderRenderer(elem, factory)

    adapter.begin()
    factory.apply_tooltip.assert_called_once_with(elem)

    # end() must NOT re-apply — that would bind the tooltip to the last child.
    factory.apply_tooltip.reset_mock()
    adapter.end(opened=True)
    factory.apply_tooltip.assert_not_called()


def test_group_adapter_applies_tooltip_after_end_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The group's bbox becomes one hoverable item only after end_vertical, so the
    # tooltip must attach in end(), strictly after the close.
    fake_imgui = MagicMock()
    monkeypatch.setattr(group_module, "imgui", fake_imgui)
    factory = MagicMock()
    elem = GroupElement(id="g", tooltip="hint")  # layout defaults to "rows"
    adapter = ImGuiGroupRenderer(elem, factory)

    order = MagicMock()
    order.attach_mock(fake_imgui.end_vertical, "end_vertical")
    order.attach_mock(factory.apply_tooltip, "apply_tooltip")
    adapter.end(opened=True)

    assert [call[0] for call in order.mock_calls] == ["end_vertical", "apply_tooltip"]
    factory.apply_tooltip.assert_called_once_with(elem)


def test_tab_bar_adapter_paints_no_tooltip_no_whole_bar_item() -> None:
    # A tab bar has only per-tab items and no single whole-bar hover target, so
    # painting the tooltip would bind it to the last tab. It is not painted; the
    # field round-trips without a target. (Old code wrongly applied it in end.)
    factory = MagicMock()
    elem = TabBarElement(id="tb", tooltip="hint")
    adapter = ImGuiTabBarRenderer(elem, factory)

    adapter.end(opened=False)

    factory.apply_tooltip.assert_not_called()


# -- dialog renderer (GL-free surface) -------------------------------------


def test_dialog_renderer_latch_keys_derive_from_element_id() -> None:
    factory = _factory()
    renderer = ImGuiDialogRenderer(DialogElement(id="dlg", title="?"), factory)
    assert renderer._open_key == "dlg__open"
    assert renderer._dismiss_key == "dlg__dismissed"


def test_dialog_begin_returns_false_and_clears_latches_when_hidden() -> None:
    ws = WidgetState()
    factory = _factory(ws)
    dialog = DialogElement(id="dlg", title="?")
    dialog.model.close()  # model no longer visible
    ws.set("dlg__open", 1)
    ws.set("dlg__dismissed", 1)

    renderer = ImGuiDialogRenderer(dialog, factory)
    # Hidden model: begin short-circuits to False without touching ImGui.
    assert renderer.begin() is False
    assert renderer._was_open is False
    assert ws.get("dlg__open") == 0
    assert ws.get("dlg__dismissed") == 0


def test_dialog_external_close_fires_model_close_cascade() -> None:
    ws = WidgetState()
    factory = _factory(ws)
    dialog = DialogElement(id="dlg", title="?")
    removed: list[str] = []
    dialog.add_observer(removed.append)

    renderer = ImGuiDialogRenderer(dialog, factory)
    renderer._handle_external_close()

    # Escape/outside close dismisses the model and fires the mark_removed cascade.
    assert dialog.visible is False
    assert dialog.removed is True
    assert removed == ["removed"]
    assert ws.get("dlg__open") == 0
    assert ws.get("dlg__dismissed") == 1


def test_dialog_end_fires_external_close_when_was_open_and_not_opened() -> None:
    # was_open=True this-frame-not-opened == Escape/outside close → dismiss.
    ws = WidgetState()
    dialog = DialogElement(id="dlg", title="?")
    removed: list[str] = []
    dialog.add_observer(removed.append)

    renderer = ImGuiDialogRenderer(dialog, _factory(ws))
    renderer._was_open = True
    renderer.end(opened=False)  # opened=False → no end_popup, GL-free

    assert dialog.visible is False
    assert dialog.removed is True
    assert removed == ["removed"]
    assert ws.get("dlg__dismissed") == 1


def test_dialog_end_does_not_dismiss_a_never_opened_dialog() -> None:
    # Regression guard: was_open=False must NOT spuriously dismiss the model.
    ws = WidgetState()
    dialog = DialogElement(id="dlg", title="?")
    removed: list[str] = []
    dialog.add_observer(removed.append)

    renderer = ImGuiDialogRenderer(dialog, _factory(ws))
    renderer._was_open = False
    renderer.end(opened=False)

    assert dialog.visible is True
    assert dialog.removed is False
    assert removed == []
