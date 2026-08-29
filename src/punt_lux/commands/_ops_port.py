"""``OpsPort`` -- the operations surface a command reads through.

Split out of ``_result`` (DES-065 OO paydown): the port is a structural
*family* contract -- what any operations facade must answer to stand in for
one -- while ``CommandResult`` and ``Ctx`` are value shapes a command
produces and consumes. Different reasons to change belong in different
modules (oo.md: "Families share by protocol, not base class").
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from punt_lux.operations import OpError, Pong

__all__ = ["OpsPort"]


@runtime_checkable
class OpsPort(Protocol):
    """The operations surface a command reads through.

    Every method a command calls appears here. ``Operations`` (luxd's typed
    facade) satisfies it structurally; ``LuxRestClient`` satisfies the same
    method shapes for the operations it exposes, so a CLI or library caller
    can build a :class:`~punt_lux.commands._ctx.Ctx` around either side of the
    process boundary and reach one shared command instance. The port widens
    as commands land in .3.
    """

    def ping(self, wait: float | None = None) -> Pong | OpError:
        """Round-trip a display ping bounded by ``wait`` seconds."""
        ...
