"""WireTreeDecoder — turn a submitted wire tree into elements, or say why not.

The wire boundary of the render path. Element kinds are open and each decodes
itself, so a malformed one raises out of its codec; that is a rejection of the
submission, not a fault of the engine, and this is the one place that translates
between the two. The catch is deliberately narrow — only the decode runs inside
it, so a store miss raised later still surfaces as the bug it is.

The factory is connection-scoped: an element that publishes does so as the
connection that submitted it, so the decode is keyed by the caller.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, cast, final

from punt_lux.operations.models.common import OpError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from punt_lux.domain.element import Element as DomainElement
    from punt_lux.domain.ids import ConnectionId
    from punt_lux.operations.ports import ElementFactoryFor

__all__ = ["WireTreeDecoder"]


@final
class WireTreeDecoder:
    """Decode wire element dicts into domain elements for one connection."""

    _element_factory: ElementFactoryFor
    __slots__ = ("_element_factory",)

    def __new__(cls, element_factory: ElementFactoryFor) -> Self:
        self = super().__new__(cls)
        self._element_factory = element_factory
        return self

    def decode(
        self, wire: Sequence[dict[str, object]], owner: ConnectionId
    ) -> Sequence[DomainElement] | OpError:
        """Decode every element in ``wire``, or return the first malformed one.

        A ``ValueError`` or ``TypeError`` out of a codec is the element saying it
        was given something it cannot be — the caller's input, so it comes back as
        a rejection. Nothing else is caught: only the decode runs inside the try,
        so a fault raised anywhere else stays the engine bug it is.
        """
        factory = self._element_factory(owner)
        try:
            decoded = [factory.element_from_dict(element) for element in wire]
        except (ValueError, TypeError) as exc:
            return OpError(code="rejected", reason=str(exc))
        # The wire Element is structurally the domain Element; the cast bridges
        # list invariance across that crossing (PY-TS-12).
        return cast("Sequence[DomainElement]", decoded)
