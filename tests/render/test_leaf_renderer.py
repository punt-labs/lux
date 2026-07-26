"""LeafRenderer records each leaf's geometry from the one place both paths reach.

The template ``paint`` paints the widget and tooltip inside the geometry
``measuring`` group, which records the leaf's rect when the group closes —
recording lives on the adapter, the single point ``elem.render()`` and
``_render_via_factory`` both call, so a top-level or ABC-nested leaf is captured,
not only a legacy-nested one. Two guards: the record happens after the whole
paint (so the group bounds it and a tooltip cannot poison the rect), and every
leaf adapter the factory dispatches inherits the template, so no leaf kind can be
added without its geometry captured.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Self, cast, final

import pytest

from punt_lux.display.renderers.imgui.button import ImGuiButtonRenderer
from punt_lux.display.renderers.imgui.checkbox import ImGuiCheckboxRenderer
from punt_lux.display.renderers.imgui.color_picker import ImGuiColorPickerRenderer
from punt_lux.display.renderers.imgui.combo import ImGuiComboRenderer
from punt_lux.display.renderers.imgui.image import ImGuiImageRenderer
from punt_lux.display.renderers.imgui.input_number import ImGuiInputNumberRenderer
from punt_lux.display.renderers.imgui.input_text import ImGuiInputTextRenderer
from punt_lux.display.renderers.imgui.leaf import LeafRenderer
from punt_lux.display.renderers.imgui.markdown import ImGuiMarkdownRenderer
from punt_lux.display.renderers.imgui.progress import ImGuiProgressRenderer
from punt_lux.display.renderers.imgui.radio import ImGuiRadioRenderer
from punt_lux.display.renderers.imgui.selectable import ImGuiSelectableRenderer
from punt_lux.display.renderers.imgui.separator import ImGuiSeparatorRenderer
from punt_lux.display.renderers.imgui.slider import ImGuiSliderRenderer
from punt_lux.display.renderers.imgui.spinner import ImGuiSpinnerRenderer
from punt_lux.display.renderers.imgui.text import ImGuiTextRenderer
from punt_lux.display.renderers.imgui.window import ImGuiWindowRenderer
from punt_lux.protocol.elements.text import TextElement

if TYPE_CHECKING:
    from collections.abc import Generator

    from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory

# Every leaf kind the factory dispatches: each must inherit the recording base.
_LEAF_ADAPTERS = [
    ImGuiTextRenderer,
    ImGuiButtonRenderer,
    ImGuiCheckboxRenderer,
    ImGuiInputTextRenderer,
    ImGuiInputNumberRenderer,
    ImGuiProgressRenderer,
    ImGuiMarkdownRenderer,
    ImGuiSpinnerRenderer,
    ImGuiSeparatorRenderer,
    ImGuiImageRenderer,
    ImGuiSliderRenderer,
    ImGuiColorPickerRenderer,
    ImGuiComboRenderer,
    ImGuiRadioRenderer,
    ImGuiSelectableRenderer,
]


class _CaptureSpy:
    """A geometry-capture stand-in whose ``measuring`` records the id on exit."""

    recorded: list[str]
    _order: list[str]
    __slots__ = ("_order", "recorded")

    def __new__(cls, order: list[str]) -> Self:
        self = super().__new__(cls)
        self.recorded = []
        self._order = order
        return self

    @contextmanager
    def measuring(self, element_id: str) -> Generator[None]:
        try:
            yield
        finally:
            self.recorded.append(element_id)
            self._order.append("record")


class _FactorySpy:
    """A factory stand-in exposing the geometry capture and a tooltip spy."""

    geometry: _CaptureSpy
    tooltipped: list[object]
    order: list[str]
    __slots__ = ("geometry", "order", "tooltipped")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.order = []
        self.geometry = _CaptureSpy(self.order)
        self.tooltipped = []
        return self

    def apply_tooltip(self, elem: object) -> None:
        self.tooltipped.append(elem)
        self.order.append("tooltip")


@final
class _SpyLeaf(LeafRenderer[TextElement]):
    """A concrete leaf whose widget hook just records that it ran."""

    _order: list[str]
    __slots__ = ("_order",)

    def __new__(cls, elem: TextElement, factory: object, order: list[str]) -> Self:
        self = super().__new__(cls, elem, cast("ImGuiRendererFactory", factory))
        self._order = order
        return self

    def _paint_widget(self) -> None:
        self._order.append("widget")


def test_paint_groups_widget_and_tooltip_then_records() -> None:
    factory = _FactorySpy()
    leaf = _SpyLeaf(TextElement(id="leaf-1", content="x"), factory, factory.order)

    leaf.paint()

    # Widget and tooltip both paint inside the measuring group; the rect is
    # recorded only when the group closes, after both — so the group bounds the
    # whole leaf and a hover tooltip's last-item write cannot poison the record.
    assert factory.order == ["widget", "tooltip", "record"]
    assert factory.geometry.recorded == ["leaf-1"]
    assert len(factory.tooltipped) == 1


@pytest.mark.parametrize("adapter", _LEAF_ADAPTERS)
def test_every_leaf_adapter_inherits_the_recording_base(adapter: type) -> None:
    assert issubclass(adapter, LeafRenderer)


def test_a_container_adapter_is_not_a_leaf_renderer() -> None:
    assert not issubclass(ImGuiWindowRenderer, LeafRenderer)
