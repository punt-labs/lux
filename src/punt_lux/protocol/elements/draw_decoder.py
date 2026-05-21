"""``DrawCommandDecoder`` — wire-dict → typed-``DrawCommand`` decoder.

The decoder holds a registry of one factory callable per
``DrawCommandKind``. Each factory is the ``from_wire`` classmethod of
the corresponding ``*Cmd`` class — decoding lives on the class that
owns the data, not in a parallel module of free functions.

``decode`` validates the ``cmd`` field, looks up the factory, and
delegates. The decoder is an instance, not a classmethod, so callers
(and tests) can construct a fresh decoder with a narrower or stubbed
registry. ``DrawCommandDecoder.default()`` returns a module-level
singleton populated with every ``*Cmd.from_wire`` — that is the one
``DrawElement`` uses.

Every public path requires an ``index`` (the position of the command
in the parent list). There is no ``int | None`` here — tests that
exercise a single command pass an arbitrary index like ``0``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final, Protocol, Self

from punt_lux.protocol.elements.draw_command_kind import (
    DrawCommand,
    DrawCommandKind,
)
from punt_lux.protocol.elements.draw_commands_curve import BezierCubicCmd
from punt_lux.protocol.elements.draw_commands_line import LineCmd, PolylineCmd
from punt_lux.protocol.elements.draw_commands_shape import (
    CircleCmd,
    RectCmd,
    TriangleCmd,
)
from punt_lux.protocol.elements.draw_commands_text import TextCmd
from punt_lux.protocol.elements.draw_wire import WireContext

__all__ = ["DrawCommandDecoder"]


class _CommandFactory(Protocol):
    """``*Cmd.from_wire`` classmethod signature — the one factory shape."""

    def __call__(self, d: Mapping[str, object], *, ctx: WireContext) -> DrawCommand: ...


class DrawCommandDecoder:
    """Instance-based decoder for draw-command wire dicts.

    Each factory is a ``*Cmd.from_wire`` classmethod bound to a
    ``DrawCommandKind``. Tests can construct a fresh decoder with one
    stub factory to exercise edge cases without touching class state.
    """

    _factories: dict[DrawCommandKind, _CommandFactory]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._factories = {}
        return self

    @classmethod
    def default(cls) -> DrawCommandDecoder:
        """Return the populated singleton used by ``DrawElement``.

        The singleton is built once at module import (see ``_DEFAULT``
        at the bottom of this module) — this classmethod is a typed
        accessor.  Subclasses that need their own populated decoder
        should construct one explicitly via the constructor and call
        ``register`` per kind; the parent singleton is intentionally
        not shared up the MRO.
        """
        return _DEFAULT

    def register(self, kind: DrawCommandKind, factory: _CommandFactory) -> None:
        """Bind a factory callable to a wire kind. Raises on duplicate."""
        if kind in self._factories:
            msg = f"draw command factory already registered for {kind.value!r}"
            raise ValueError(msg)
        self._factories[kind] = factory

    def decode(self, d: Mapping[str, object], index: int) -> DrawCommand:
        """Decode a wire dict at ``index`` into a typed ``DrawCommand``.

        ``index`` is the position of this command in the parent list.
        Tests that exercise a single command may pass any non-negative
        integer; the value only affects error message formatting.
        """
        pre_ctx = WireContext.at_index(index)
        raw_kind = d.get("cmd")
        if not isinstance(raw_kind, str) or not raw_kind:
            msg = f"{pre_ctx.prefix} missing or invalid 'cmd' field; got {dict(d)!r}"
            raise ValueError(msg)
        try:
            kind = DrawCommandKind(raw_kind)
        except ValueError as exc:
            raise self._unknown_kind_error(pre_ctx, raw_kind) from exc
        factory = self._factories.get(kind)
        if factory is None:
            raise self._unknown_kind_error(pre_ctx, raw_kind)
        ctx = WireContext.for_indexed(kind.value, index)
        return factory(d, ctx=ctx)

    @property
    def registered_kinds(self) -> frozenset[DrawCommandKind]:
        """Return the set of registered wire kinds."""
        return frozenset(self._factories)

    def _unknown_kind_error(self, pre_ctx: WireContext, raw_kind: str) -> ValueError:
        known = ", ".join(sorted(k.value for k in self._factories))
        msg = (
            f"{pre_ctx.prefix} has unknown 'cmd' {raw_kind!r}; expected one of: {known}"
        )
        return ValueError(msg)


# Populated module-level singleton — every *Cmd.from_wire is registered
# eagerly at import time so a broken registration fails fast.
_DEFAULT: Final = DrawCommandDecoder()
_DEFAULT.register(DrawCommandKind.LINE, LineCmd.from_wire)
_DEFAULT.register(DrawCommandKind.RECT, RectCmd.from_wire)
_DEFAULT.register(DrawCommandKind.CIRCLE, CircleCmd.from_wire)
_DEFAULT.register(DrawCommandKind.TRIANGLE, TriangleCmd.from_wire)
_DEFAULT.register(DrawCommandKind.TEXT, TextCmd.from_wire)
_DEFAULT.register(DrawCommandKind.POLYLINE, PolylineCmd.from_wire)
_DEFAULT.register(DrawCommandKind.BEZIER_CUBIC, BezierCubicCmd.from_wire)
