"""Assemble the ABC spec for every migrated leaf kind (container kinds next door)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.wire.model.standalone_button_handler import (
    build_standalone_button_handler_decoder,
)
from punt_lux.wire.model.standalone_color_picker_handler import (
    build_standalone_color_picker_handler_decoder,
)
from punt_lux.wire.model.standalone_input_number_handler import (
    build_standalone_input_number_handler_decoder,
)
from punt_lux.wire.model.standalone_input_text_handler import (
    build_standalone_input_text_handler_decoder,
)
from punt_lux.wire.model.standalone_row_selection_handler import (
    build_standalone_row_selection_handler_decoder,
)
from punt_lux.wire.model.standalone_slider_handler import (
    build_standalone_slider_handler_decoder,
)

from .abc_kind_codec import KindCodec
from .abc_kind_specs import DialogKindSpec
from .abc_leaf_spec import LeafKindSpec
from .abc_static_leaf_kinds import StaticLeafKinds
from .button import ButtonElement
from .button_codec import JsonButtonDecoder, JsonButtonEncoder
from .button_sugar import ButtonWireSugar
from .checkbox import CheckboxElement
from .checkbox_codec import JsonCheckboxDecoder, JsonCheckboxEncoder
from .color_picker import ColorPickerElement
from .color_picker_codec import JsonColorPickerDecoder, JsonColorPickerEncoder
from .combo import ComboElement
from .combo_codec import JsonComboDecoder, JsonComboEncoder
from .dialog import DialogElement
from .dialog_codec import JsonDialogDecoder, JsonDialogEncoder
from .input_number import InputNumberElement
from .input_number_codec import JsonInputNumberDecoder, JsonInputNumberEncoder
from .input_text import InputTextElement
from .input_text_codec import JsonInputTextDecoder, JsonInputTextEncoder
from .radio import RadioElement
from .radio_codec import JsonRadioDecoder, JsonRadioEncoder
from .selectable import SelectableElement
from .selectable_codec import JsonSelectableDecoder, JsonSelectableEncoder
from .slider import SliderElement
from .slider_codec import JsonSliderDecoder, JsonSliderEncoder
from .table import TableElement
from .table_codec import JsonTableDecoder, JsonTableEncoder
from .value_change_handlers import build_standalone_value_handler_decoder

if TYPE_CHECKING:
    from .abc_kind_spec import AbcKindSpec

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
            *StaticLeafKinds.specs(),
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
                wants_publish_sink=True,
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
