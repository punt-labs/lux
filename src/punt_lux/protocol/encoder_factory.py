"""JsonEncoderFactory — stateless outbound wire encoder, dispatched by type.

``encode(elem)`` routes ``type(elem)`` via the shared ``AbcElementRegistry``'s
encoder dispatch to a per-kind encoder. Adding a migrated kind adds a spec to
the registration table, not an arm here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.protocol.elements.abc_kind_table import DEFAULT_ABC_REGISTRY

if TYPE_CHECKING:
    from punt_lux.protocol.elements.abc_kind_spec import KindEncoder

__all__ = ["JsonEncoderFactory"]


class JsonEncoderFactory:
    """Dispatch elements to per-kind encoders by their concrete type."""

    __slots__ = ("_dispatch",)

    _dispatch: tuple[tuple[type, KindEncoder], ...]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._dispatch = DEFAULT_ABC_REGISTRY.encoder_dispatch()
        return self

    def encode(self, elem: object) -> dict[str, object]:
        """Dispatch by ``type(elem)`` to the per-kind encoder."""
        for element_type, encode in self._dispatch:
            if isinstance(elem, element_type):
                return encode(elem)
        msg = f"JsonEncoderFactory has no encoder for {type(elem).__name__}"
        raise TypeError(msg)
