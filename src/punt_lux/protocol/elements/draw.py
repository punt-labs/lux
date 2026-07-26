"""DrawElement — a display-only 2D canvas on the Element ABC.

ABC subclass with keyword-only ``__new__``. Sentinel defaults on
``renderer_factory`` and ``emit`` (shared through ``abc_di_defaults``) keep
direct construction compiling; the Display binds the real factory in its
post-receive rebind. A draw canvas is a leaf: its ``commands`` are a typed
``DrawCommand`` value family (no more ``list[dict]``), not child elements, so it
overrides none of the render-template hooks and its children walk is empty.

Command well-formedness is a wire-boundary concern: ``DrawCommandDecoder`` (via
``decode_all``) raises ``ValueError`` on a malformed command — a non-mapping
entry, an unknown ``cmd``, or a bad coordinate — before any DrawElement exists.
Nothing survives decode that ``validate`` would need to re-check, so ``validate``
inherits the leaf default (no residual invariant), the same ruling ``tree``
follows for its ``TreeNode`` family.

The codec body lives in ``draw_codec.py``; ``to_dict`` and ``from_dict`` remain
short delegators so the ``domain.element.Element`` Protocol stays satisfied.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self, cast

from punt_lux.domain.element_abc import Element
from punt_lux.protocol.elements.abc_di_defaults import NO_EMIT, RAISING_FACTORY
from punt_lux.protocol.elements.draw_codec import JsonDrawDecoder, JsonDrawEncoder
from punt_lux.protocol.elements.draw_decoder import DrawCommandDecoder
from punt_lux.protocol.elements.patch_field import PatchField

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol.elements.draw_command_kind import DrawCommand
    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["DrawElement"]


class DrawElement(Element):
    """A 2D canvas painted from a tuple of typed ``DrawCommand`` values.

    PY-TS-14 OK: ``bg_color`` stays ``str | None`` — absence is the documented
    contract for "no background fill, use the renderer default"; ``tooltip``
    likewise means no tooltip. ``width``/``height`` are total ``int`` pixel sizes
    and ``commands`` a total tuple, so neither needs an Optional.
    """

    _id: str
    _width: int
    _height: int
    _bg_color: str | None
    _commands: tuple[DrawCommand, ...]
    _tooltip: str | None
    _kind: Literal["draw"]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory = RAISING_FACTORY,
        emit: Emit = NO_EMIT,
        id: str,
        width: int = 400,
        height: int = 300,
        bg_color: str | None = None,
        commands: tuple[DrawCommand, ...] = (),
        tooltip: str | None = None,
    ) -> Self:
        self = super().__new__(cls, renderer_factory=renderer_factory, emit=emit)
        self._id = id
        self._width = width
        self._height = height
        self._bg_color = bg_color
        self._commands = commands
        self._tooltip = tooltip
        self._kind = "draw"
        return self

    @property
    def id(self) -> str:
        """Return the element's stable identity within its enclosing Scene."""
        return self._id

    @property
    def kind(self) -> Literal["draw"]:
        """Return the wire discriminator — always ``"draw"``."""
        return self._kind

    @property
    def width(self) -> int:
        """Return the canvas width in pixels."""
        return self._width

    @property
    def height(self) -> int:
        """Return the canvas height in pixels."""
        return self._height

    @property
    def bg_color(self) -> str | None:
        """Return the background fill color, or ``None`` for no fill."""
        return self._bg_color

    @property
    def commands(self) -> tuple[DrawCommand, ...]:
        """Return the draw commands, each a typed ``DrawCommand`` value."""
        return self._commands

    @property
    def tooltip(self) -> str | None:
        """Return the hover-tooltip text, or ``None`` for no tooltip."""
        return self._tooltip

    def _set_width(self, value: object) -> None:
        """Replace the canvas width (used by ``Element.apply_patch``)."""
        self._width = PatchField("width").as_int(value)

    def _set_height(self, value: object) -> None:
        """Replace the canvas height (used by ``Element.apply_patch``)."""
        self._height = PatchField("height").as_int(value)

    def _set_bg_color(self, value: object) -> None:
        """Replace the background color (used by ``Element.apply_patch``)."""
        self._bg_color = PatchField("bg_color").as_optional_str(value)

    def _set_commands(self, value: object) -> None:
        """Replace the commands, rejecting a malformed one (``Element.apply_patch``)."""
        self._commands = DrawCommandDecoder.default().decode_all(value, "commands")

    def _set_tooltip(self, value: object) -> None:
        """Replace the tooltip text (used by ``Element.apply_patch``)."""
        self._tooltip = PatchField("tooltip").as_optional_str(value)

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible wire representation."""
        return JsonDrawEncoder().encode(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        """Construct a DrawElement from a JSON-decoded mapping."""
        decoder = JsonDrawDecoder(
            renderer_factory=RAISING_FACTORY, emit=NO_EMIT, element_cls=cls
        )
        # ``element_cls=cls`` guarantees the concrete subtype; the decoder's
        # annotation is the supertype, so narrow to ``Self`` for the Protocol.
        return cast("Self", decoder.decode(d))

    def resolved_props(self) -> Mapping[str, object]:
        """Return the full resolved state, including defaulted fields."""
        return {
            "width": self._width,
            "height": self._height,
            "bg_color": self._bg_color,
            "commands": [cmd.to_dict() for cmd in self._commands],
            "tooltip": self._tooltip,
        }
