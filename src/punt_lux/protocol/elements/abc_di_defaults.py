"""Construction-time DI sentinels shared by the Element-ABC kinds.

Direct ``TextElement(id=..., content=...)`` construction (tests, agent
fixtures) supplies no tier injection, so the ABC element ``__new__``
signatures default ``renderer_factory`` and ``emit`` to these sentinels.
The wire decode path always passes real tier values, so the runtime DI
shape on the wire path is unchanged.

``RAISING_FACTORY`` fails loud on any ``elem.render()`` from a non-display
tier (see ``RaisingRendererFactory``); ``NO_EMIT`` is the Null-Object emit
channel (PY-DP-9) for the Hub tier, which never emits.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.protocol.renderers.raising import RaisingRendererFactory

if TYPE_CHECKING:
    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["NO_EMIT", "RAISING_FACTORY", "NoEmit"]


class NoEmit:
    """No-op emit channel — the Hub tier never emits (PY-DP-9 Null Object)."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def __call__(self, _msg: object) -> None:
        """Discard the message — this tier has no emit sink."""


RAISING_FACTORY: RendererFactory = RaisingRendererFactory()
NO_EMIT: Emit = NoEmit()
