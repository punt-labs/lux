"""Assemble the ABC spec for every migrated leaf kind (container kinds next door)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.protocol.elements.abc_kind_codec import KindCodec
from punt_lux.protocol.elements.abc_kind_specs import DialogKindSpec
from punt_lux.protocol.elements.abc_leaf_spec import LeafKindSpec
from punt_lux.protocol.elements.button import ButtonElement
from punt_lux.protocol.elements.button_codec import JsonButtonDecoder, JsonButtonEncoder
from punt_lux.protocol.elements.button_sugar import ButtonWireSugar
from punt_lux.protocol.elements.checkbox import CheckboxElement
from punt_lux.protocol.elements.checkbox_codec import (
    JsonCheckboxDecoder,
    JsonCheckboxEncoder,
)
from punt_lux.protocol.elements.color_picker import ColorPickerElement
from punt_lux.protocol.elements.color_picker_codec import (
    JsonColorPickerDecoder,
    JsonColorPickerEncoder,
)
from punt_lux.protocol.elements.combo import ComboElement
from punt_lux.protocol.elements.combo_codec import JsonComboDecoder, JsonComboEncoder
from punt_lux.protocol.elements.dialog import DialogElement
from punt_lux.protocol.elements.dialog_codec import JsonDialogDecoder, JsonDialogEncoder
from punt_lux.protocol.elements.draw import DrawElement
from punt_lux.protocol.elements.draw_codec import JsonDrawDecoder, JsonDrawEncoder
from punt_lux.protocol.elements.image import ImageElement
from punt_lux.protocol.elements.image_codec import JsonImageDecoder, JsonImageEncoder
from punt_lux.protocol.elements.input_number import InputNumberElement
from punt_lux.protocol.elements.input_number_codec import (
    JsonInputNumberDecoder,
    JsonInputNumberEncoder,
)
from punt_lux.protocol.elements.input_text import InputTextElement
from punt_lux.protocol.elements.input_text_codec import (
    JsonInputTextDecoder,
    JsonInputTextEncoder,
)
from punt_lux.protocol.elements.markdown import MarkdownElement
from punt_lux.protocol.elements.markdown_codec import (
    JsonMarkdownDecoder,
    JsonMarkdownEncoder,
)
from punt_lux.protocol.elements.plot import PlotElement
from punt_lux.protocol.elements.plot_codec import JsonPlotDecoder, JsonPlotEncoder
from punt_lux.protocol.elements.progress import ProgressElement
from punt_lux.protocol.elements.progress_codec import (
    JsonProgressDecoder,
    JsonProgressEncoder,
)
from punt_lux.protocol.elements.radio import RadioElement
from punt_lux.protocol.elements.radio_codec import JsonRadioDecoder, JsonRadioEncoder
from punt_lux.protocol.elements.selectable import SelectableElement
from punt_lux.protocol.elements.selectable_codec import (
    JsonSelectableDecoder,
    JsonSelectableEncoder,
)
from punt_lux.protocol.elements.separator import SeparatorElement
from punt_lux.protocol.elements.separator_codec import (
    JsonSeparatorDecoder,
    JsonSeparatorEncoder,
)
from punt_lux.protocol.elements.slider import SliderElement
from punt_lux.protocol.elements.slider_codec import JsonSliderDecoder, JsonSliderEncoder
from punt_lux.protocol.elements.spinner import SpinnerElement
from punt_lux.protocol.elements.spinner_codec import (
    JsonSpinnerDecoder,
    JsonSpinnerEncoder,
)
from punt_lux.protocol.elements.table import TableElement
from punt_lux.protocol.elements.table_codec import JsonTableDecoder, JsonTableEncoder
from punt_lux.protocol.elements.text import TextElement
from punt_lux.protocol.elements.text_codec import JsonTextDecoder, JsonTextEncoder
from punt_lux.protocol.elements.tree import TreeElement
from punt_lux.protocol.elements.tree_codec import JsonTreeDecoder, JsonTreeEncoder
from punt_lux.protocol.elements.value_change_handlers import (
    build_standalone_value_handler_decoder,
)
from punt_lux.protocol.standalone_button_handler import (
    build_standalone_button_handler_decoder,
)
from punt_lux.protocol.standalone_color_picker_handler import (
    build_standalone_color_picker_handler_decoder,
)
from punt_lux.protocol.standalone_input_number_handler import (
    build_standalone_input_number_handler_decoder,
)
from punt_lux.protocol.standalone_input_text_handler import (
    build_standalone_input_text_handler_decoder,
)
from punt_lux.protocol.standalone_row_selection_handler import (
    build_standalone_row_selection_handler_decoder,
)
from punt_lux.protocol.standalone_slider_handler import (
    build_standalone_slider_handler_decoder,
)

if TYPE_CHECKING:
    from punt_lux.protocol.elements.abc_kind_spec import AbcKindSpec

__all__ = ["DefaultLeafKinds"]


class DefaultLeafKinds:
    """Assembles the leaf-path spec for every migrated leaf kind."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    @staticmethod
    def specs() -> list[AbcKindSpec]:
        """Return the leaf specs: static leaves, Dialog, then interactive inputs."""
        return [
            LeafKindSpec(
                kind="text",
                codec=KindCodec(TextElement, JsonTextDecoder, JsonTextEncoder().encode),
            ),
            LeafKindSpec(
                kind="progress",
                codec=KindCodec(
                    ProgressElement, JsonProgressDecoder, JsonProgressEncoder().encode
                ),
            ),
            LeafKindSpec(
                kind="markdown",
                codec=KindCodec(
                    MarkdownElement, JsonMarkdownDecoder, JsonMarkdownEncoder().encode
                ),
            ),
            LeafKindSpec(
                kind="spinner",
                codec=KindCodec(
                    SpinnerElement, JsonSpinnerDecoder, JsonSpinnerEncoder().encode
                ),
            ),
            LeafKindSpec(
                kind="separator",
                codec=KindCodec(
                    SeparatorElement,
                    JsonSeparatorDecoder,
                    JsonSeparatorEncoder().encode,
                ),
            ),
            LeafKindSpec(
                kind="image",
                codec=KindCodec(
                    ImageElement, JsonImageDecoder, JsonImageEncoder().encode
                ),
            ),
            LeafKindSpec(
                kind="tree",
                codec=KindCodec(TreeElement, JsonTreeDecoder, JsonTreeEncoder().encode),
            ),
            LeafKindSpec(
                kind="plot",
                codec=KindCodec(PlotElement, JsonPlotDecoder, JsonPlotEncoder().encode),
            ),
            LeafKindSpec(
                kind="draw",
                codec=KindCodec(DrawElement, JsonDrawDecoder, JsonDrawEncoder().encode),
            ),
            DialogKindSpec(
                codec=KindCodec(
                    DialogElement, JsonDialogDecoder, JsonDialogEncoder().encode
                ),
            ),
            LeafKindSpec(
                kind="button",
                codec=KindCodec(
                    ButtonElement, JsonButtonDecoder, JsonButtonEncoder().encode
                ),
                handler_builder=build_standalone_button_handler_decoder,
                pre_decode=ButtonWireSugar.canonicalize,
            ),
            LeafKindSpec(
                kind="checkbox",
                codec=KindCodec(
                    CheckboxElement, JsonCheckboxDecoder, JsonCheckboxEncoder().encode
                ),
                handler_builder=build_standalone_value_handler_decoder,
            ),
            LeafKindSpec(
                kind="input_text",
                codec=KindCodec(
                    InputTextElement,
                    JsonInputTextDecoder,
                    JsonInputTextEncoder().encode,
                ),
                handler_builder=build_standalone_input_text_handler_decoder,
            ),
            LeafKindSpec(
                kind="input_number",
                codec=KindCodec(
                    InputNumberElement,
                    JsonInputNumberDecoder,
                    JsonInputNumberEncoder().encode,
                ),
                handler_builder=build_standalone_input_number_handler_decoder,
            ),
            LeafKindSpec(
                kind="slider",
                codec=KindCodec(
                    SliderElement, JsonSliderDecoder, JsonSliderEncoder().encode
                ),
                handler_builder=build_standalone_slider_handler_decoder,
            ),
            LeafKindSpec(
                kind="color_picker",
                codec=KindCodec(
                    ColorPickerElement,
                    JsonColorPickerDecoder,
                    JsonColorPickerEncoder().encode,
                ),
                handler_builder=build_standalone_color_picker_handler_decoder,
            ),
            LeafKindSpec(
                kind="combo",
                codec=KindCodec(
                    ComboElement, JsonComboDecoder, JsonComboEncoder().encode
                ),
                handler_builder=build_standalone_value_handler_decoder,
            ),
            LeafKindSpec(
                kind="radio",
                codec=KindCodec(
                    RadioElement, JsonRadioDecoder, JsonRadioEncoder().encode
                ),
                handler_builder=build_standalone_value_handler_decoder,
            ),
            LeafKindSpec(
                kind="selectable",
                codec=KindCodec(
                    SelectableElement,
                    JsonSelectableDecoder,
                    JsonSelectableEncoder().encode,
                ),
                handler_builder=build_standalone_value_handler_decoder,
            ),
            LeafKindSpec(
                kind="table",
                codec=KindCodec(
                    TableElement, JsonTableDecoder, JsonTableEncoder().encode
                ),
                handler_builder=build_standalone_row_selection_handler_decoder,
            ),
        ]
