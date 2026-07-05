"""Nested-in-legacy ABC leaves dispatch to their per-kind renderer.

During the fork's mixed period a legacy container (group, window, ...)
recurses its children through ``ElementRenderer.render_element``. The four
migrated ABC kinds stay in the legacy dispatch tables so a nested
``TextElement`` / ``ButtonElement`` / ``CheckboxElement`` paints via the
per-kind renderer — not the ``[unsupported element: ...]`` fallback.

These tests assert the dispatch *decision* with stub renderers, GL-free:
``_dispatch_native`` returns True and calls the matching per-kind renderer,
which is the exact branch that avoids the fallback. Driving real
``render_element`` would call into ImGui (``apply_tooltip``), which segfaults
without a GL context.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple
from unittest.mock import MagicMock

from punt_lux.display.element_renderer import ElementRenderer
from punt_lux.display.table_renderer import TableRenderer
from punt_lux.display.texture_cache import TextureCache
from punt_lux.protocol.elements.button import ButtonElement
from punt_lux.protocol.elements.checkbox import CheckboxElement
from punt_lux.protocol.elements.dialog import DialogElement
from punt_lux.protocol.elements.layout import LegacyGroupElement, WindowElement
from punt_lux.protocol.elements.text import TextElement
from punt_lux.protocol.messages.remote_invocation import RemoteEventHandlerInvocation
from punt_lux.scene.widget_state import WidgetState

if TYPE_CHECKING:
    import pytest


def _no_emit_event(_msg: RemoteEventHandlerInvocation) -> None:
    """No-op interaction emit."""


def _no_check_dirty(_window_id: str) -> bool:
    return False


class _Stubbed(NamedTuple):
    """An ElementRenderer with its leaf renderers replaced by mocks."""

    renderer: ElementRenderer
    text: MagicMock
    button: MagicMock
    checkbox: MagicMock


def _stubbed() -> _Stubbed:
    widget_state = WidgetState()
    er = ElementRenderer(
        widget_state=widget_state,
        texture_cache=TextureCache(),
        table_renderer=TableRenderer(
            widget_state=widget_state, emit_event=_no_emit_event
        ),
        emit_event=_no_emit_event,
        check_dirty_window=_no_check_dirty,
    )
    # Replace the per-kind renderers with mocks so the dispatch decision is
    # GL-free (their real ``render`` calls into ImGui).
    text, button, checkbox = MagicMock(), MagicMock(), MagicMock()
    er._text_renderer = text
    er._button_renderer = button
    er._checkbox_renderer = checkbox
    return _Stubbed(er, text, button, checkbox)


def test_group_leaves_dispatch_to_per_kind_renderer() -> None:
    stub = _stubbed()
    text = TextElement(id="t", content="hi")
    button = ButtonElement(id="b", label="Go")
    checkbox = CheckboxElement(id="c", label="On")
    group = LegacyGroupElement(id="g", children=[text, button, checkbox])

    for child in group.children:
        # True == resolved to a per-kind renderer, NOT the unsupported fallback.
        assert stub.renderer._dispatch_native(child) is True

    stub.text.render.assert_called_once_with(text)
    stub.button.render.assert_called_once_with(button)
    stub.checkbox.render.assert_called_once_with(checkbox)


def test_window_leaves_dispatch_to_per_kind_renderer() -> None:
    stub = _stubbed()
    button = ButtonElement(id="wb", label="Go")
    window = WindowElement(id="w", children=[button])

    assert stub.renderer._dispatch_native(window.children[0]) is True
    stub.button.render.assert_called_once_with(button)


def test_dialog_key_resolves_to_render_dialog_not_fallback() -> None:
    # A dialog nested in a legacy container is NOT native, so _dispatch_native
    # returns False; the "dialog" kind then resolves through the _RENDERERS
    # table to _render_dialog — never the [unsupported element: ...] fallback.
    stub = _stubbed()
    dialog = DialogElement(id="d1", title="Confirm")
    assert stub.renderer._dispatch_native(dialog) is False
    assert stub.renderer._RENDERERS["dialog"] == "_render_dialog"


def test_dialog_render_element_skips_generic_tooltip_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A dialog resolves to _render_dialog, which applies its own tooltip via
    # ImGuiDialogRenderer.end. render_element must NOT also run the generic
    # apply_tooltip post-pass, or a dialog tooltip would be applied twice.
    stub = _stubbed()
    render_dialog, apply_tooltip = MagicMock(), MagicMock()
    monkeypatch.setattr(stub.renderer, "_render_dialog", render_dialog)
    monkeypatch.setattr(stub.renderer, "apply_tooltip", apply_tooltip)

    dialog = DialogElement(id="d1", title="Confirm", tooltip="hint")
    stub.renderer.render_element(dialog)

    render_dialog.assert_called_once_with(dialog)
    apply_tooltip.assert_not_called()


def test_non_dialog_render_element_runs_generic_tooltip_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Contrast: a non-dialog element still gets the generic apply_tooltip pass,
    # so the guard narrows to dialogs only.
    stub = _stubbed()
    apply_tooltip = MagicMock()
    monkeypatch.setattr(stub.renderer, "apply_tooltip", apply_tooltip)

    text = TextElement(id="t", content="hi", tooltip="hint")
    stub.renderer.render_element(text)

    apply_tooltip.assert_called_once_with(text)
