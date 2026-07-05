"""ImGui per-kind adapters — factory dispatch, leaf paint, dialog dismiss.

Covers the render-path-unification adapters without a live GL context.
The paint methods that call into real ImGui (a dialog's ``begin``/``end``
popup chrome) segfault without a frame, so only the GL-free surface is unit
tested here; the live interaction loops are the leader-run e2e.
"""

from __future__ import annotations

from typing import Self
from unittest.mock import MagicMock

from punt_lux.display.element_renderer import ElementRenderer
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
from punt_lux.protocol.elements.text import TextElement
from punt_lux.protocol.messages.remote_invocation import RemoteEventHandlerInvocation
from punt_lux.scene.widget_state import WidgetState


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
        element_renderer=_element_renderer(ws),
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


class _StubElementRenderer:
    """Element renderer stub exposing the narrow paint seam only."""

    button_renderer: MagicMock
    checkbox_renderer: MagicMock
    _tooltip: MagicMock

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.button_renderer = MagicMock()
        self.checkbox_renderer = MagicMock()
        self._tooltip = MagicMock()
        return self

    def apply_tooltip(self, elem: object) -> None:
        self._tooltip(elem)


class _StubFactory:
    """Factory stub exposing only ``element_renderer``."""

    _element_renderer: _StubElementRenderer

    def __new__(cls, element_renderer: _StubElementRenderer) -> Self:
        self = super().__new__(cls)
        self._element_renderer = element_renderer
        return self

    @property
    def element_renderer(self) -> _StubElementRenderer:
        return self._element_renderer


def test_button_adapter_begin_true_paint_delegates_end_noop() -> None:
    er = _StubElementRenderer()
    elem = ButtonElement(id="b", label="Go")
    adapter = ImGuiButtonRenderer(elem, _StubFactory(er))  # type: ignore[arg-type]
    assert adapter.begin() is True
    adapter.paint()
    adapter.end(opened=True)
    er.button_renderer.render.assert_called_once_with(elem)
    er._tooltip.assert_called_once_with(elem)


def test_checkbox_adapter_begin_true_paint_delegates_end_noop() -> None:
    er = _StubElementRenderer()
    elem = CheckboxElement(id="c", label="On")
    adapter = ImGuiCheckboxRenderer(elem, _StubFactory(er))  # type: ignore[arg-type]
    assert adapter.begin() is True
    adapter.paint()
    adapter.end(opened=True)
    er.checkbox_renderer.render.assert_called_once_with(elem)
    er._tooltip.assert_called_once_with(elem)


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
