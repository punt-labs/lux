"""Ordered per-kind ImGui adapter bindings, independent of shared renderer state."""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

from punt_lux.display.renderers.imgui.button import ImGuiButtonRenderer
from punt_lux.display.renderers.imgui.checkbox import ImGuiCheckboxRenderer
from punt_lux.display.renderers.imgui.collapsing_header import (
    ImGuiCollapsingHeaderRenderer,
)
from punt_lux.display.renderers.imgui.color_picker import ImGuiColorPickerRenderer
from punt_lux.display.renderers.imgui.combo import ImGuiComboRenderer
from punt_lux.display.renderers.imgui.dialog import ImGuiDialogRenderer
from punt_lux.display.renderers.imgui.draw import ImGuiDrawRenderer
from punt_lux.display.renderers.imgui.group import ImGuiGroupRenderer
from punt_lux.display.renderers.imgui.image import ImGuiImageRenderer
from punt_lux.display.renderers.imgui.input_number import ImGuiInputNumberRenderer
from punt_lux.display.renderers.imgui.input_text import ImGuiInputTextRenderer
from punt_lux.display.renderers.imgui.markdown import ImGuiMarkdownRenderer
from punt_lux.display.renderers.imgui.modal import ImGuiModalRenderer
from punt_lux.display.renderers.imgui.plot import ImGuiPlotRenderer
from punt_lux.display.renderers.imgui.progress import ImGuiProgressRenderer
from punt_lux.display.renderers.imgui.radio import ImGuiRadioRenderer
from punt_lux.display.renderers.imgui.selectable import ImGuiSelectableRenderer
from punt_lux.display.renderers.imgui.separator import ImGuiSeparatorRenderer
from punt_lux.display.renderers.imgui.slider import ImGuiSliderRenderer
from punt_lux.display.renderers.imgui.spinner import ImGuiSpinnerRenderer
from punt_lux.display.renderers.imgui.split_pane import ImGuiSplitPaneRenderer
from punt_lux.display.renderers.imgui.tab_bar import ImGuiTabBarRenderer
from punt_lux.display.renderers.imgui.table import ImGuiTableRenderer
from punt_lux.display.renderers.imgui.terminal import ImGuiTerminalRenderer
from punt_lux.display.renderers.imgui.text import ImGuiTextRenderer
from punt_lux.display.renderers.imgui.tree import ImGuiTreeRenderer
from punt_lux.display.renderers.imgui.window import ImGuiWindowRenderer
from punt_lux.wire.model.elements.button import ButtonElement
from punt_lux.wire.model.elements.checkbox import CheckboxElement
from punt_lux.wire.model.elements.collapsing_header import CollapsingHeaderElement
from punt_lux.wire.model.elements.color_picker import ColorPickerElement
from punt_lux.wire.model.elements.combo import ComboElement
from punt_lux.wire.model.elements.dialog import DialogElement
from punt_lux.wire.model.elements.draw import DrawElement
from punt_lux.wire.model.elements.group import GroupElement
from punt_lux.wire.model.elements.image import ImageElement
from punt_lux.wire.model.elements.input_number import InputNumberElement
from punt_lux.wire.model.elements.input_text import InputTextElement
from punt_lux.wire.model.elements.markdown import MarkdownElement
from punt_lux.wire.model.elements.modal import ModalElement
from punt_lux.wire.model.elements.plot import PlotElement
from punt_lux.wire.model.elements.progress import ProgressElement
from punt_lux.wire.model.elements.radio import RadioElement
from punt_lux.wire.model.elements.selectable import SelectableElement
from punt_lux.wire.model.elements.separator import SeparatorElement
from punt_lux.wire.model.elements.slider import SliderElement
from punt_lux.wire.model.elements.spinner import SpinnerElement
from punt_lux.wire.model.elements.split_pane import SplitPaneElement
from punt_lux.wire.model.elements.tab_bar import TabBarElement
from punt_lux.wire.model.elements.table import TableElement
from punt_lux.wire.model.elements.terminal import TerminalElement
from punt_lux.wire.model.elements.text import TextElement
from punt_lux.wire.model.elements.tree import TreeElement
from punt_lux.wire.model.elements.window import WindowElement
from punt_lux.wire.model.renderer import Renderer


class ImGuiRendererBindings:
    """The adapter order, including subclass-before-parent dispatch."""

    _DISPATCH: ClassVar[tuple[tuple[type, Callable[..., Renderer]], ...]] = (
        (TextElement, ImGuiTextRenderer),
        (ButtonElement, ImGuiButtonRenderer),
        (CheckboxElement, ImGuiCheckboxRenderer),
        (InputTextElement, ImGuiInputTextRenderer),
        (InputNumberElement, ImGuiInputNumberRenderer),
        (DialogElement, ImGuiDialogRenderer),
        (ModalElement, ImGuiModalRenderer),
        (WindowElement, ImGuiWindowRenderer),
        # SplitPaneElement subclasses GroupElement, so it must match first.
        (SplitPaneElement, ImGuiSplitPaneRenderer),
        (GroupElement, ImGuiGroupRenderer),
        (CollapsingHeaderElement, ImGuiCollapsingHeaderRenderer),
        (TabBarElement, ImGuiTabBarRenderer),
        (ProgressElement, ImGuiProgressRenderer),
        (MarkdownElement, ImGuiMarkdownRenderer),
        (SpinnerElement, ImGuiSpinnerRenderer),
        (TerminalElement, ImGuiTerminalRenderer),  # SPIKE
        (SeparatorElement, ImGuiSeparatorRenderer),
        (ImageElement, ImGuiImageRenderer),
        (SliderElement, ImGuiSliderRenderer),
        (ColorPickerElement, ImGuiColorPickerRenderer),
        (ComboElement, ImGuiComboRenderer),
        (RadioElement, ImGuiRadioRenderer),
        (SelectableElement, ImGuiSelectableRenderer),
        (TableElement, ImGuiTableRenderer),
        (TreeElement, ImGuiTreeRenderer),
        (PlotElement, ImGuiPlotRenderer),
        (DrawElement, ImGuiDrawRenderer),
    )

    @classmethod
    def table(cls) -> tuple[tuple[type, Callable[..., Renderer]], ...]:
        return cls._DISPATCH
