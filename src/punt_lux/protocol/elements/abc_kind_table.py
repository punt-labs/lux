"""The default ABC-kind registration table — the one file a migration edits.

``DefaultAbcKinds.build()`` registers every migrated kind's spec into a fresh
``AbcElementRegistry`` and cross-checks the result against ``AbcKindNames``.
Migrating a new kind adds one ``register(...)`` line here plus its string in
``AbcKindNames`` — no other module in the decode/encode path changes.

This module is the aggregation leaf: it imports every migrated kind's element,
decoder, encoder, and standalone-handler builder, exactly as the encoder and
element factories once did inline.
"""

from __future__ import annotations

from typing import Self

from punt_lux.protocol.elements.abc_kind_names import AbcKindNames
from punt_lux.protocol.elements.abc_kind_spec import KindCodec
from punt_lux.protocol.elements.abc_kind_specs import (
    ContainerKindSpec,
    DialogKindSpec,
    LeafKindSpec,
)
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
from punt_lux.protocol.elements.slider import SliderElement
from punt_lux.protocol.elements.slider_codec import JsonSliderDecoder, JsonSliderEncoder
from punt_lux.protocol.elements.tab_bar import TabBarElement
from punt_lux.protocol.elements.tab_bar_codec import (
    JsonTabBarDecoder,
    JsonTabBarEncoder,
)
from punt_lux.protocol.elements.text import TextElement
from punt_lux.protocol.elements.text_codec import JsonTextDecoder, JsonTextEncoder
from punt_lux.protocol.standalone_button_handler import (
    build_standalone_button_handler_decoder,
)
from punt_lux.protocol.standalone_checkbox_handler import (
    build_standalone_checkbox_handler_decoder,
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

__all__ = ["DEFAULT_ABC_REGISTRY", "DefaultAbcKinds"]


class DefaultAbcKinds:
    """Builds the production ``AbcElementRegistry`` with every migrated kind."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    @classmethod
    def build(cls) -> AbcElementRegistry:
        """Register every migrated kind and cross-check against ``AbcKindNames``."""
        registry = AbcElementRegistry()
        cls._register_static_leaves(registry)
        cls._register_handler_leaves(registry)
        cls._register_containers(registry)
        cls.verify_names(registry)
        return registry

    @staticmethod
    def _register_static_leaves(registry: AbcElementRegistry) -> None:
        """Register leaves with no handler wiring (Text, Progress) and Dialog."""
        registry.register(
            LeafKindSpec(
                kind="text",
                codec=KindCodec(TextElement, JsonTextDecoder, JsonTextEncoder().encode),
            )
        )
        registry.register(
            LeafKindSpec(
                kind="progress",
                codec=KindCodec(
                    ProgressElement, JsonProgressDecoder, JsonProgressEncoder().encode
                ),
            )
        )
        registry.register(
            DialogKindSpec(
                codec=KindCodec(
                    DialogElement, JsonDialogDecoder, JsonDialogEncoder().encode
                ),
            )
        )

    @staticmethod
    def _register_handler_leaves(registry: AbcElementRegistry) -> None:
        """Register interactive leaves whose decoders wire declarative handlers."""
        registry.register(
            LeafKindSpec(
                kind="button",
                codec=KindCodec(
                    ButtonElement, JsonButtonDecoder, JsonButtonEncoder().encode
                ),
                handler_builder=build_standalone_button_handler_decoder,
                pre_decode=ButtonWireSugar.canonicalize,
            )
        )
        registry.register(
            LeafKindSpec(
                kind="checkbox",
                codec=KindCodec(
                    CheckboxElement, JsonCheckboxDecoder, JsonCheckboxEncoder().encode
                ),
                handler_builder=build_standalone_checkbox_handler_decoder,
            )
        )
        registry.register(
            LeafKindSpec(
                kind="input_text",
                codec=KindCodec(
                    InputTextElement,
                    JsonInputTextDecoder,
                    JsonInputTextEncoder().encode,
                ),
                handler_builder=build_standalone_input_text_handler_decoder,
            )
        )
        registry.register(
            LeafKindSpec(
                kind="input_number",
                codec=KindCodec(
                    InputNumberElement,
                    JsonInputNumberDecoder,
                    JsonInputNumberEncoder().encode,
                ),
                handler_builder=build_standalone_input_number_handler_decoder,
            )
        )
        registry.register(
            LeafKindSpec(
                kind="slider",
                codec=KindCodec(
                    SliderElement, JsonSliderDecoder, JsonSliderEncoder().encode
                ),
                handler_builder=build_standalone_slider_handler_decoder,
            )
        )
        registry.register(
            LeafKindSpec(
                kind="color_picker",
                codec=KindCodec(
                    ColorPickerElement,
                    JsonColorPickerDecoder,
                    JsonColorPickerEncoder().encode,
                ),
                handler_builder=build_standalone_color_picker_handler_decoder,
            )
        )

    @staticmethod
    def _register_containers(registry: AbcElementRegistry) -> None:
        """Register the conditionally-ABC container kinds."""
        registry.register(
            ContainerKindSpec(
                kind="group",
                codec=KindCodec(
                    GroupElement, JsonGroupDecoder, JsonGroupEncoder().encode
                ),
            )
        )
        registry.register(
            ContainerKindSpec(
                kind="collapsing_header",
                codec=KindCodec(
                    CollapsingHeaderElement,
                    JsonCollapsingHeaderDecoder,
                    JsonCollapsingHeaderEncoder().encode,
                ),
                handler_builder=build_standalone_collapsing_header_handler_decoder,
            )
        )
        registry.register(
            ContainerKindSpec(
                kind="tab_bar",
                codec=KindCodec(
                    TabBarElement, JsonTabBarDecoder, JsonTabBarEncoder().encode
                ),
                handler_builder=build_standalone_tab_bar_handler_decoder,
            )
        )

    @staticmethod
    def verify_names(registry: AbcElementRegistry) -> None:
        """Fail loud if the registry and ``AbcKindNames`` disagree on the kind set.

        The two data homes exist because the import-light gate cannot see
        element classes; this cross-check turns any drift between them into an
        import-time error rather than a latent wire bug.
        """
        if registry.all_kinds != AbcKindNames.MIGRATED_ABC_KINDS:
            diff = registry.all_kinds ^ AbcKindNames.MIGRATED_ABC_KINDS
            msg = f"ABC registry and AbcKindNames disagree on migrated kinds: {diff}"
            raise RuntimeError(msg)
        if registry.container_kinds != AbcKindNames.ABC_CONTAINER_KINDS:
            diff = registry.container_kinds ^ AbcKindNames.ABC_CONTAINER_KINDS
            msg = f"ABC registry and AbcKindNames disagree on container kinds: {diff}"
            raise RuntimeError(msg)


DEFAULT_ABC_REGISTRY: AbcElementRegistry = DefaultAbcKinds.build()
