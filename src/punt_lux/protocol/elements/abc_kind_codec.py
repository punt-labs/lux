"""``KindCodec`` — one migrated kind's wire codec triple, owning its encode call.

Separated from the DI binding and the ``AbcKindSpec`` contract so the value
object that the three spec shapes all compose lives in its own focused module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from punt_lux.protocol.elements.abc_kind_spec import KindEncoder

__all__ = ["KindCodec"]


@dataclass(frozen=True, slots=True)
class KindCodec:
    """One kind's wire codec: element class, decoder class, encoder.

    ``decoder_cls`` is a ``JsonXDecoder`` class constructed dynamically at the
    wire boundary — the same dynamic dispatch ``ElementCodec`` performs — so it
    is typed ``Any`` here (PY-TS-9). Owns ``encode`` so the three spec shapes
    share one implementation rather than repeating the call (PY-OO-5).
    """

    element_cls: type
    decoder_cls: Any  # JsonXDecoder class; constructed at the wire boundary
    encoder: KindEncoder

    def encode(self, elem: object) -> dict[str, object]:
        """Serialize ``elem`` through this kind's encoder."""
        return self.encoder(elem)
