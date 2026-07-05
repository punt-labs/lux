"""JsonEncoderFactory — top-level wire encoder dispatching by element type.

The outbound dispatcher. Stateless — one instance shared across the
process; each ``encode(elem)`` call routes to the per-kind encoder for
``type(elem)``.

Ships Text, Button, Checkbox, and Dialog dispatch. Additional kinds
register as each family migrates from the legacy ``ElementCodec`` path
to the per-kind encoders.
"""

from __future__ import annotations

from typing import Self

from punt_lux.protocol.elements.button import ButtonElement
from punt_lux.protocol.elements.button_codec import JsonButtonEncoder
from punt_lux.protocol.elements.checkbox import CheckboxElement
from punt_lux.protocol.elements.checkbox_codec import JsonCheckboxEncoder
from punt_lux.protocol.elements.dialog import DialogElement
from punt_lux.protocol.elements.dialog_codec import JsonDialogEncoder
from punt_lux.protocol.elements.group import GroupElement
from punt_lux.protocol.elements.group_codec import JsonGroupEncoder
from punt_lux.protocol.elements.text import TextElement
from punt_lux.protocol.elements.text_codec import JsonTextEncoder

__all__ = ["JsonEncoderFactory"]


class JsonEncoderFactory:
    """Dispatch elements to per-kind encoders by their concrete type."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def encode(self, elem: object) -> dict[str, object]:
        """Dispatch by ``type(elem)`` to the per-kind encoder."""
        if isinstance(elem, TextElement):
            return JsonTextEncoder().encode(elem)
        if isinstance(elem, ButtonElement):
            return JsonButtonEncoder().encode(elem)
        if isinstance(elem, CheckboxElement):
            return JsonCheckboxEncoder().encode(elem)
        if isinstance(elem, DialogElement):
            return JsonDialogEncoder().encode(elem)
        if isinstance(elem, GroupElement):
            return JsonGroupEncoder().encode(elem)
        msg = f"JsonEncoderFactory has no encoder for {type(elem).__name__}"
        raise TypeError(msg)
