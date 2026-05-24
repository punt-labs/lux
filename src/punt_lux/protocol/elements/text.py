"""TextElement — io-model text block on the Element ABC.

Per docs/oo-refactor/pr3-v2.1-design.md §4: rewritten from the PR-2
frozen dataclass to an ABC subclass with ``__new__``-keyword-only
construction. Sentinel defaults on ``renderer_factory`` and ``emit``
(D1) keep the existing keyword call sites compiling; decode through
``JsonTextDecoder`` always passes real values, so the runtime DI shape
on the wire path is unchanged.

The codec body lives in ``text_codec.py`` (``JsonTextEncoder`` /
``JsonTextDecoder``); ``to_dict`` and ``from_dict`` remain on the class
as ≤ 3-line delegators (D5) so the runtime-checkable
``domain.element.Element`` Protocol stays satisfied.

``_patch`` is inherited from ``Element`` ABC (D6); ``_set_<field>``
setters cover the patch fields exercised by the scene patch path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self, cast

from punt_lux.domain.element_abc import Element
from punt_lux.protocol.elements.text_codec import JsonTextDecoder, JsonTextEncoder
from punt_lux.protocol.renderers.null import NullRendererFactory

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["TextElement"]


# Module-level sentinels — the Hub-tier null objects (per
# pr3-v2.1-design.md §4 D1). The decode path through ``JsonTextDecoder``
# always passes real values; these defaults exist so existing call sites
# (100+ across tests and apps) that construct ``TextElement(id=..., content=...)``
# directly keep compiling. PR 12's sweep tightens these back to required
# kwargs once every family has migrated.
_NULL_FACTORY: RendererFactory = NullRendererFactory()


def _no_emit(_msg: object) -> None:
    """Sentinel emit channel — Hub-tier no-op (PY-DP-9 Null Object)."""


class TextElement(Element):
    """A text block.

    PY-TS-14 OK: ``style`` and ``tooltip`` stay ``str | None`` —
    ``style`` is the deferred Literal-flip (D3 — snapshot parity needs
    permissive accept of arbitrary style strings), ``tooltip`` absence
    is the documented contract.

    ``color`` flips from ``str | None`` to ``str = ""`` (D4) — the empty
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
        renderer_factory: RendererFactory = _NULL_FACTORY,
        emit: Emit = _no_emit,
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

    # -- minimal setters for the scene patch path (D6) ---------------------
    #
    # ``Element._patch`` dispatches JSON-decoded values straight to these
    # setters, so each ``value`` arrives as ``object`` and PY-EH-1 demands
    # boundary validation before we assign to a narrowly-typed attribute.

    @staticmethod
    def _str_or_raise(value: object, field: str) -> str:
        """Return ``value`` as ``str`` or raise ``TypeError`` (PY-EH-1)."""
        if not isinstance(value, str):
            msg = f"{field} must be str, got {type(value).__name__}"
            raise TypeError(msg)
        return value

    @staticmethod
    def _opt_str_or_raise(value: object, field: str) -> str | None:
        """Return ``value`` as ``str | None`` or raise ``TypeError`` (PY-EH-1)."""
        if value is None or isinstance(value, str):
            return value
        msg = f"{field} must be str or None, got {type(value).__name__}"
        raise TypeError(msg)

    def _set_content(self, value: object) -> None:
        """Replace the text content (used by ``Element._patch``)."""
        self._content = self._str_or_raise(value, "content")

    def _set_style(self, value: object) -> None:
        """Replace the style hint (used by ``Element._patch``)."""
        self._style = self._opt_str_or_raise(value, "style")

    def _set_tooltip(self, value: object) -> None:
        """Replace the tooltip text (used by ``Element._patch``)."""
        self._tooltip = self._opt_str_or_raise(value, "tooltip")

    def _set_color(self, value: object) -> None:
        """Replace the color (NF1: ``null`` coerces to "" matching decoder)."""
        self._color = "" if value is None else self._str_or_raise(value, "color")

    # -- codec delegators (D5) ---------------------------------------------

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible wire representation."""
        return JsonTextEncoder().encode(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        """Construct a TextElement from a JSON-decoded mapping."""
        decoder = JsonTextDecoder(
            renderer_factory=_NULL_FACTORY, emit=_no_emit, element_cls=cls
        )
        # ``element_cls=cls`` guarantees the decoder builds the concrete
        # subtype; the decoder's annotation is the supertype TextElement
        # so narrow back to ``Self`` for the Protocol contract.
        return cast("Self", decoder.decode(d))
