"""The default ABC-kind registration table — the one file a migration edits.

``DefaultAbcKinds.build()`` assembles every migrated kind's spec, verifies the
table with ``AbcKindVerifier`` (name and capability parity), then registers them
into a fresh ``AbcElementRegistry``. Migrating a new kind adds one spec here plus
its string in ``AbcKindNames`` — no other module in the decode/encode path
changes.

This module is the aggregation leaf: it imports every migrated kind's element,
decoder, encoder, and standalone-handler builder, exactly as the encoder and
element factories once did inline.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.protocol.elements.abc_kind_codec import KindCodec
from punt_lux.protocol.elements.abc_kind_specs import (
    ContainerKindSpec,
    DialogKindSpec,
)
from punt_lux.protocol.elements.abc_kind_verify import AbcKindVerifier
from punt_lux.protocol.elements.abc_leaf_spec import LeafKindSpec
from punt_lux.protocol.elements.abc_registry import AbcElementRegistry
from punt_lux.protocol.elements.button import ButtonElement
from punt_lux.protocol.elements.button_codec import JsonButtonDecoder, JsonButtonEncoder
from punt_lux.protocol.elements.button_sugar import ButtonWireSugar
from punt_lux.protocol.elements.checkbox import CheckboxElement
from punt_lux.protocol.elements.checkbox_codec import (
    JsonCheckboxDecoder,
    JsonCheckboxEncoder,
)
from punt_lux.protocol.elements.collapsing_header import CollapsingHeaderElement
from punt_lux.protocol.elements.collapsing_header_codec import (
    JsonCollapsingHeaderDecoder,
    JsonCollapsingHeaderEncoder,
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
from punt_lux.protocol.elements.group import GroupElement
from punt_lux.protocol.elements.group_codec import JsonGroupDecoder, JsonGroupEncoder
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
from punt_lux.protocol.elements.slider import SliderElement
from punt_lux.protocol.elements.slider_codec import JsonSliderDecoder, JsonSliderEncoder
from punt_lux.protocol.elements.tab_bar import TabBarElement
from punt_lux.protocol.elements.tab_bar_codec import (
    JsonTabBarDecoder,
    JsonTabBarEncoder,
)
from punt_lux.protocol.elements.text import TextElement
from punt_lux.protocol.elements.text_codec import JsonTextDecoder, JsonTextEncoder
from punt_lux.protocol.elements.value_change_handlers import (
    build_standalone_value_handler_decoder,
)
from punt_lux.protocol.standalone_button_handler import (
    build_standalone_button_handler_decoder,
)
from punt_lux.protocol.standalone_collapsing_header_handler import (
    build_standalone_collapsing_header_handler_decoder,
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
from punt_lux.protocol.standalone_slider_handler import (
    build_standalone_slider_handler_decoder,
)
from punt_lux.protocol.standalone_tab_bar_handler import (
    build_standalone_tab_bar_handler_decoder,
)

if TYPE_CHECKING:
    from punt_lux.protocol.elements.abc_kind_spec import AbcKindSpec

__all__ = ["DEFAULT_ABC_REGISTRY", "DefaultAbcKinds"]


class DefaultAbcKinds:
    """Builds the production ``AbcElementRegistry`` with every migrated kind."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    @classmethod
    def build(cls) -> AbcElementRegistry:
        """Register every migrated kind, then verify the registry."""
        registry = AbcElementRegistry()
        for spec in (*cls._leaf_specs(), *cls._container_specs()):
            registry.register(spec)
        AbcKindVerifier.verify(registry)
        return registry

    @staticmethod
    def _leaf_specs() -> list[AbcKindSpec]:
        """Return the leaf specs: static (Text, Progress), Dialog, interactive."""
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
        ]

    @staticmethod
    def _container_specs() -> list[AbcKindSpec]:
        """Return the conditionally-ABC container specs."""
        return [
            ContainerKindSpec(
                kind="group",
                codec=KindCodec(
                    GroupElement, JsonGroupDecoder, JsonGroupEncoder().encode
                ),
            ),
            ContainerKindSpec(
                kind="collapsing_header",
                codec=KindCodec(
                    CollapsingHeaderElement,
                    JsonCollapsingHeaderDecoder,
                    JsonCollapsingHeaderEncoder().encode,
                ),
                handler_builder=build_standalone_collapsing_header_handler_decoder,
            ),
            ContainerKindSpec(
                kind="tab_bar",
                codec=KindCodec(
                    TabBarElement, JsonTabBarDecoder, JsonTabBarEncoder().encode
                ),
                handler_builder=build_standalone_tab_bar_handler_decoder,
            ),
        ]


DEFAULT_ABC_REGISTRY: AbcElementRegistry = DefaultAbcKinds.build()
