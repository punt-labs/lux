"""JsonEncoderFactory — stateless outbound wire encoder, dispatched by type.

``encode(elem)`` routes ``type(elem)`` via ``_DISPATCH`` to a per-kind encoder.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar, Self

from punt_lux.protocol.elements.button import ButtonElement
from punt_lux.protocol.elements.button_codec import JsonButtonEncoder
from punt_lux.protocol.elements.checkbox import CheckboxElement
from punt_lux.protocol.elements.checkbox_codec import JsonCheckboxEncoder
from punt_lux.protocol.elements.collapsing_header import CollapsingHeaderElement
from punt_lux.protocol.elements.collapsing_header_codec import (
    JsonCollapsingHeaderEncoder,
)
from punt_lux.protocol.elements.dialog import DialogElement
from punt_lux.protocol.elements.dialog_codec import JsonDialogEncoder
from punt_lux.protocol.elements.group import GroupElement
from punt_lux.protocol.elements.group_codec import JsonGroupEncoder
from punt_lux.protocol.elements.progress import ProgressElement
from punt_lux.protocol.elements.progress_codec import JsonProgressEncoder
from punt_lux.protocol.elements.tab_bar import TabBarElement
from punt_lux.protocol.elements.tab_bar_codec import JsonTabBarEncoder
from punt_lux.protocol.elements.text import TextElement
from punt_lux.protocol.elements.text_codec import JsonTextEncoder

__all__ = ["JsonEncoderFactory"]


class JsonEncoderFactory:
    """Dispatch elements to per-kind encoders by their concrete type."""

    __slots__ = ()

    # Element type -> the per-kind stateless encoder's bound ``encode``.
    _DISPATCH: ClassVar[tuple[tuple[type, Callable[..., dict[str, object]]], ...]] = (
        (TextElement, JsonTextEncoder().encode),
        (ButtonElement, JsonButtonEncoder().encode),
        (CheckboxElement, JsonCheckboxEncoder().encode),
        (DialogElement, JsonDialogEncoder().encode),
        (GroupElement, JsonGroupEncoder().encode),
        (CollapsingHeaderElement, JsonCollapsingHeaderEncoder().encode),
        (TabBarElement, JsonTabBarEncoder().encode),
        (ProgressElement, JsonProgressEncoder().encode),
    )

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def encode(self, elem: object) -> dict[str, object]:
        """Dispatch by ``type(elem)`` to the per-kind encoder."""
        for element_type, encode in self._DISPATCH:
            if isinstance(elem, element_type):
                return encode(elem)
        msg = f"JsonEncoderFactory has no encoder for {type(elem).__name__}"
        raise TypeError(msg)
