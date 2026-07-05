"""TextElement — text block on the Element ABC.

ABC subclass with ``__new__``-keyword-only construction. Sentinel
defaults on ``renderer_factory`` and ``emit`` (shared through
``abc_di_defaults``) keep keyword call sites compiling. Decode passes the
tier's sentinel factory; the display-capable factory is bound later by the
Display's post-receive rebind (``Element.bind_renderer_factory``), not the decoder.

The codec body lives in ``text_codec.py`` (``JsonTextEncoder`` /
``JsonTextDecoder``); ``to_dict`` and ``from_dict`` remain on the class
as ≤ 3-line delegators so the runtime-checkable
``domain.element.Element`` Protocol stays satisfied.

``apply_patch`` is inherited from ``Element`` ABC; ``_set_<field>``
setters cover the patch fields exercised by the scene patch path and
coerce the wire value through ``PatchField`` at the boundary (PY-EH-1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self, cast

from punt_lux.domain.element_abc import Element
from punt_lux.protocol.elements.abc_di_defaults import NO_EMIT, RAISING_FACTORY
from punt_lux.protocol.elements.patch_field import PatchField
from punt_lux.protocol.elements.text_codec import JsonTextDecoder, JsonTextEncoder

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["TextElement"]


class TextElement(Element):
    """A text block.

    PY-TS-14 OK: ``style`` and ``tooltip`` stay ``str | None`` —
    ``style`` stays permissive so snapshot parity can accept arbitrary
    style strings, ``tooltip`` absence is the documented contract.

    ``color`` is ``str = ""`` rather than ``str | None`` — the empty
    string is the discriminated "no override" state; the renderer's
    ``parse_hex_color(elem.color) if elem.color else None`` treats
    empty/None equivalently, so the byte-on-wire shape is unchanged
    (the encoder omits ``color`` when it's the default).
    """

    _id: str
    _content: str
    _style: str | None
    _tooltip: str | None
    _color: str
    _kind: Literal["text"]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory = RAISING_FACTORY,
        emit: Emit = NO_EMIT,
        id: str,
        content: str,
        style: str | None = None,
        tooltip: str | None = None,
        color: str = "",
    ) -> Self:
        self = super().__new__(cls, renderer_factory=renderer_factory, emit=emit)
        self._id = id
        self._content = content
        self._style = style
        self._tooltip = tooltip
        self._color = color
        self._kind = "text"
        return self

    # -- read-only accessors (the wire-facing surface) ----------------------

    @property
    def id(self) -> str:
        """Return the element's stable identity within its enclosing Scene."""
        return self._id

    @property
    def kind(self) -> Literal["text"]:
        """Return the wire discriminator — always ``"text"``."""
        return self._kind

    @property
    def content(self) -> str:
        """Return the text content the renderer paints."""
        return self._content

    @property
    def style(self) -> str | None:
        """Return the rendering style hint, or ``None`` for the default."""
        return self._style

    @property
    def tooltip(self) -> str | None:
        """Return the hover-tooltip text, or ``None`` for no tooltip."""
        return self._tooltip

    @property
    def color(self) -> str:
        """Return the foreground color, or ``""`` for the renderer default."""
        return self._color

    # -- minimal setters for the scene patch path ---------------------------
    #
    # ``Element.apply_patch`` dispatches JSON-decoded values straight to these
    # setters, so each ``value`` arrives as ``object`` and PY-EH-1 demands
    # boundary validation before we assign to a narrowly-typed attribute.

    def _set_content(self, value: object) -> None:
        """Replace the text content (used by ``Element.apply_patch``)."""
        self._content = PatchField("content").as_str(value)

    def _set_style(self, value: object) -> None:
        """Replace the style hint (used by ``Element.apply_patch``)."""
        self._style = PatchField("style").as_optional_str(value)

    def _set_tooltip(self, value: object) -> None:
        """Replace the tooltip text (used by ``Element.apply_patch``)."""
        self._tooltip = PatchField("tooltip").as_optional_str(value)

    def _set_color(self, value: object) -> None:
        """Replace the color (``null`` coerces to "" matching decoder)."""
        self._color = "" if value is None else PatchField("color").as_str(value)

    # -- codec delegators ---------------------------------------------------

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible wire representation."""
        return JsonTextEncoder().encode(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        """Construct a TextElement from a JSON-decoded mapping."""
        decoder = JsonTextDecoder(
            renderer_factory=RAISING_FACTORY, emit=NO_EMIT, element_cls=cls
        )
        # ``element_cls=cls`` guarantees the decoder builds the concrete
        # subtype; the decoder's annotation is the supertype TextElement
        # so narrow back to ``Self`` for the Protocol contract.
        return cast("Self", decoder.decode(d))

    # -- introspection (Inspectable) ---------------------------------------

    def resolved_props(self) -> Mapping[str, object]:
        """Return the full resolved state, including defaulted fields."""
        return {
            "content": self._content,
            "style": self._style,
            "tooltip": self._tooltip,
            "color": self._color,
        }
