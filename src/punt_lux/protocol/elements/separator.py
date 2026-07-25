"""SeparatorElement — a visual divider on the Element ABC.

ABC subclass with keyword-only ``__new__``. Sentinel defaults on
``renderer_factory`` and ``emit`` (shared through ``abc_di_defaults``) keep
direct construction compiling; the Display binds the real factory in its
post-receive rebind. A separator is a leaf — no children, no handlers, no
interaction — so it overrides none of the render-template hooks and inherits
the empty ``validate()`` default (a divider has no invalid state).

Separator is the one anonymous-capable kind: it may arrive with an empty id
(``SeparatorElement()``), which the wire codec omits. It therefore implements
``Anonymizable`` so the dual-write pump can ask it for an id-stamped copy
rather than route it through ``dataclasses.replace`` (an ABC leaf cannot).

The codec body lives in ``separator_codec.py`` (``JsonSeparatorEncoder`` /
``JsonSeparatorDecoder``); ``to_dict`` and ``from_dict`` remain on the class
as short delegators so the runtime-checkable ``domain.element.Element``
Protocol stays satisfied.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self, cast

from punt_lux.domain.element_abc import Element
from punt_lux.protocol.elements.abc_di_defaults import NO_EMIT, RAISING_FACTORY
from punt_lux.protocol.elements.patch_field import PatchField
from punt_lux.protocol.elements.separator_codec import (
    JsonSeparatorDecoder,
    JsonSeparatorEncoder,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["SeparatorElement"]


class SeparatorElement(Element):
    """A visual divider.

    PY-TS-14 OK: ``tooltip`` stays ``str | None`` — absence is the documented
    contract for no tooltip. ``id`` defaults to ``""`` — the anonymous sentinel
    (a value meaning "no caller-supplied identity"), not the absence of a value;
    the pump assigns a synthesized id when the divider reaches the domain store.
    """

    _id: str
    _tooltip: str | None
    _kind: Literal["separator"]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory = RAISING_FACTORY,
        emit: Emit = NO_EMIT,
        id: str = "",
        tooltip: str | None = None,
    ) -> Self:
        self = super().__new__(cls, renderer_factory=renderer_factory, emit=emit)
        self._id = id
        self._tooltip = tooltip
        self._kind = "separator"
        return self

    @property
    def id(self) -> str:
        """Return the element's identity, or ``""`` when anonymous."""
        return self._id

    @property
    def kind(self) -> Literal["separator"]:
        """Return the wire discriminator — always ``"separator"``."""
        return self._kind

    @property
    def tooltip(self) -> str | None:
        """Return the hover-tooltip text, or ``None`` for no tooltip."""
        return self._tooltip

    def _set_tooltip(self, value: object) -> None:
        """Replace the tooltip text (used by ``Element.apply_patch``)."""
        self._tooltip = PatchField("tooltip").as_optional_str(value)

    def with_synthesized_id(self, new_id: str) -> Self:
        """Return a copy carrying ``new_id`` — the ``Anonymizable`` capability.

        A leaf has no handlers, observers, or children to carry over, so a
        fresh construction preserving the injected DI is a faithful copy. The
        original stays untouched so the wire/renderer view keeps its empty id.
        """
        return type(self)(
            renderer_factory=self._renderer_factory,
            emit=self._emit,
            id=new_id,
            tooltip=self._tooltip,
        )

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible wire representation."""
        return JsonSeparatorEncoder().encode(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        """Construct a SeparatorElement from a JSON-decoded mapping."""
        decoder = JsonSeparatorDecoder(
            renderer_factory=RAISING_FACTORY, emit=NO_EMIT, element_cls=cls
        )
        # ``element_cls=cls`` guarantees the concrete subtype; the decoder's
        # annotation is the supertype, so narrow to ``Self`` for the Protocol.
        return cast("Self", decoder.decode(d))

    def resolved_props(self) -> Mapping[str, object]:
        """Return the full resolved state, including defaulted fields."""
        return {"tooltip": self._tooltip}
