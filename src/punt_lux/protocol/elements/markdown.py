"""MarkdownElement — a block of rendered markdown text on the Element ABC.

ABC subclass with keyword-only ``__new__``. Sentinel defaults on
``renderer_factory`` and ``emit`` (shared through ``abc_di_defaults``) keep
direct construction compiling; the Display binds the real factory in its
post-receive rebind. Markdown is a leaf — no children, no handlers, no
interaction — so it overrides none of the render-template hooks and inherits
the empty ``validate()`` default (a markdown block has no invalid state; its
one field is type-checked at the decode boundary).

The codec body lives in ``markdown_codec.py`` (``JsonMarkdownEncoder`` /
``JsonMarkdownDecoder``); ``to_dict`` and ``from_dict`` remain on the class
as short delegators so the runtime-checkable ``domain.element.Element``
Protocol stays satisfied.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self, cast

from punt_lux.domain.element_abc import Element
from punt_lux.protocol.elements.abc_di_defaults import NO_EMIT, RAISING_FACTORY
from punt_lux.protocol.elements.markdown_codec import (
    JsonMarkdownDecoder,
    JsonMarkdownEncoder,
)
from punt_lux.protocol.elements.patch_field import PatchField

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["MarkdownElement"]


class MarkdownElement(Element):
    """A block of rendered markdown text.

    PY-TS-14 OK: ``tooltip`` stays ``str | None`` — absence is the documented
    contract for no tooltip. ``content`` is a total ``str``.
    """

    _id: str
    _content: str
    _tooltip: str | None
    _kind: Literal["markdown"]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory = RAISING_FACTORY,
        emit: Emit = NO_EMIT,
        id: str,
        content: str,
        tooltip: str | None = None,
    ) -> Self:
        self = super().__new__(cls, renderer_factory=renderer_factory, emit=emit)
        self._id = id
        self._content = content
        self._tooltip = tooltip
        self._kind = "markdown"
        return self

    @property
    def id(self) -> str:
        """Return the element's stable identity within its enclosing Scene."""
        return self._id

    @property
    def kind(self) -> Literal["markdown"]:
        """Return the wire discriminator — always ``"markdown"``."""
        return self._kind

    @property
    def content(self) -> str:
        """Return the markdown source the renderer paints."""
        return self._content

    @property
    def tooltip(self) -> str | None:
        """Return the hover-tooltip text, or ``None`` for no tooltip."""
        return self._tooltip

    def _set_content(self, value: object) -> None:
        """Replace the markdown source (used by ``Element.apply_patch``)."""
        self._content = PatchField("content").as_str(value)

    def _set_tooltip(self, value: object) -> None:
        """Replace the tooltip text (used by ``Element.apply_patch``)."""
        self._tooltip = PatchField("tooltip").as_optional_str(value)

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible wire representation."""
        return JsonMarkdownEncoder().encode(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        """Construct a MarkdownElement from a JSON-decoded mapping."""
        decoder = JsonMarkdownDecoder(
            renderer_factory=RAISING_FACTORY, emit=NO_EMIT, element_cls=cls
        )
        # ``element_cls=cls`` guarantees the concrete subtype; the decoder's
        # annotation is the supertype, so narrow to ``Self`` for the Protocol.
        return cast("Self", decoder.decode(d))

    def resolved_props(self) -> Mapping[str, object]:
        """Return the full resolved state, including defaulted fields."""
        return {"content": self._content, "tooltip": self._tooltip}
