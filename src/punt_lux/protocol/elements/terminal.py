"""TerminalElement — SPIKE: a live terminal leaf backed by libghostty-vt.

Spike-only (spike/terminal-ghostty). The element is pure placement: it names
a terminal ``session`` and, optionally, the ``command`` to start in it. The
bytes use a direct latency baseline; production traffic goes via the Hub.
The Display holds a replica; ``luxd-pty`` owns the PTY and streams snapshots
and output bytes. ``rows``/``cols`` fit the space and are not on the wire.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self, cast

from punt_lux.domain.element_abc import Element
from punt_lux.protocol.elements._util import strip_none
from punt_lux.protocol.elements.abc_di_defaults import NO_EMIT, RAISING_FACTORY
from punt_lux.protocol.elements.element_wire import ElementWireContext
from punt_lux.protocol.elements.patch_field import PatchField

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["JsonTerminalDecoder", "JsonTerminalEncoder", "TerminalElement"]


class TerminalElement(Element):
    """A terminal: ``session`` names the PTY; ``command`` starts it (default shell)."""

    _id: str
    _session: str
    _command: str
    _height: float
    _tooltip: str | None
    _kind: Literal["terminal"]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory = RAISING_FACTORY,
        emit: Emit = NO_EMIT,
        id: str,
        session: str = "",
        command: str = "",
        height: float = 0.0,
        tooltip: str | None = None,
    ) -> Self:
        self = super().__new__(cls, renderer_factory=renderer_factory, emit=emit)
        self._id = id
        self._session = session or id  # a terminal's session defaults to its id
        self._command = command
        self._height = height
        self._tooltip = tooltip
        self._kind = "terminal"
        return self

    @property
    def id(self) -> str:
        """Return the element's stable identity within its enclosing Scene."""
        return self._id

    @property
    def kind(self) -> Literal["terminal"]:
        """Return the wire discriminator — always ``"terminal"``."""
        return self._kind

    @property
    def session(self) -> str:
        """Return the daemon session name, independent of Display lifetime."""
        return self._session

    @property
    def command(self) -> str:
        """Return the command line to start, or ``""`` for the user's shell."""
        return self._command

    @property
    def height(self) -> float:
        """Return the requested height in points; ``0`` fills the space left."""
        return self._height

    @property
    def tooltip(self) -> str | None:
        """Return the hover-tooltip text, or ``None`` for no tooltip."""
        return self._tooltip

    def _set_height(self, value: object) -> None:
        self._height = PatchField("height").as_number(value)

    def _set_tooltip(self, value: object) -> None:
        self._tooltip = PatchField("tooltip").as_optional_str(value)

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible wire representation."""
        return JsonTerminalEncoder().encode(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        """Construct a TerminalElement from a JSON-decoded mapping."""
        decoder = JsonTerminalDecoder(
            renderer_factory=RAISING_FACTORY, emit=NO_EMIT, element_cls=cls
        )
        return cast("Self", decoder.decode(d))

    def resolved_props(self) -> Mapping[str, object]:
        """Return the full resolved state, including defaulted fields."""
        return {
            "session": self._session,
            "command": self._command,
            "height": self._height,
            "tooltip": self._tooltip,
        }


class JsonTerminalDecoder:
    """Decode a wire dict to a ``TerminalElement`` with the tier's DI injected."""

    _rf: RendererFactory
    _emit: Emit
    _cls: type[TerminalElement]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory,
        emit: Emit,
        element_cls: type[TerminalElement] = TerminalElement,
    ) -> Self:
        self = super().__new__(cls)
        self._rf = renderer_factory
        self._emit = emit
        self._cls = element_cls
        return self

    def decode(self, raw: Mapping[str, object]) -> TerminalElement:
        """Construct a TerminalElement from a JSON-decoded mapping."""
        ctx = ElementWireContext.for_kind("terminal")
        return self._cls(
            renderer_factory=self._rf,
            emit=self._emit,
            id=ctx.require_id(raw),
            session=ctx.optional_str(raw, "session", default=""),
            command=ctx.optional_str(raw, "command", default=""),
            height=ctx.optional_number(raw, "height", default=0.0),
            tooltip=ctx.optional_nullable_str(raw, "tooltip"),
        )


class JsonTerminalEncoder:
    """Encode a ``TerminalElement`` to its JSON-compatible wire dict."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def encode(self, elem: TerminalElement) -> dict[str, object]:
        """Serialize a TerminalElement to a JSON-compatible dict."""
        return strip_none(
            {
                "kind": elem.kind,
                "id": elem.id,
                "session": elem.session,
                "command": elem.command or None,
                "height": elem.height or None,
                "tooltip": elem.tooltip,
            }
        )
