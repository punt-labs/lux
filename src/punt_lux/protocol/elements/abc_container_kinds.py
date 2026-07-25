"""The migrated container kinds — every conditionally-ABC container's spec.

``DefaultContainerKinds.specs()`` is where a newly-migrated container kind adds
one spec; a container decodes onto its ABC class only when its whole subtree is
migrated-ABC.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.protocol.elements.abc_kind_codec import KindCodec
from punt_lux.protocol.elements.abc_kind_specs import ContainerKindSpec
from punt_lux.protocol.elements.collapsing_header import CollapsingHeaderElement
from punt_lux.protocol.elements.collapsing_header_codec import (
    JsonCollapsingHeaderDecoder,
    JsonCollapsingHeaderEncoder,
)
from punt_lux.protocol.elements.group import GroupElement
from punt_lux.protocol.elements.group_codec import JsonGroupDecoder, JsonGroupEncoder
from punt_lux.protocol.elements.modal import ModalElement
from punt_lux.protocol.elements.modal_codec import JsonModalDecoder, JsonModalEncoder
from punt_lux.protocol.elements.tab_bar import TabBarElement
from punt_lux.protocol.elements.tab_bar_codec import (
    JsonTabBarDecoder,
    JsonTabBarEncoder,
)
from punt_lux.protocol.standalone_collapsing_header_handler import (
    build_standalone_collapsing_header_handler_decoder,
)
from punt_lux.protocol.standalone_modal_handler import (
    build_standalone_modal_handler_decoder,
)
from punt_lux.protocol.standalone_tab_bar_handler import (
    build_standalone_tab_bar_handler_decoder,
)

if TYPE_CHECKING:
    from punt_lux.protocol.elements.abc_kind_spec import AbcKindSpec

__all__ = ["DefaultContainerKinds"]


class DefaultContainerKinds:
    """Assembles the container-path spec for every migrated container kind."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    @staticmethod
    def specs() -> list[AbcKindSpec]:
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
            ContainerKindSpec(
                kind="modal",
                codec=KindCodec(
                    ModalElement, JsonModalDecoder, JsonModalEncoder().encode
                ),
                handler_builder=build_standalone_modal_handler_decoder,
            ),
        ]
