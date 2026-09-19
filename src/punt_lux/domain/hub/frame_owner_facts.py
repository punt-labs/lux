"""FrameOwnerFactsReader — the port the replicator resolves a scene's owner
facts on, and the pieces that make the domain safe to use before it is bound.

The replicator's scene-send path is domain code and the dependency arrow runs
operations -> domain, never back (mirrors ``ClientDetailsRenderer`` /
``DetailsBinding`` for the retiring Details command, ``client_details_port.py``
/ ``details_binding.py``). So the domain declares what it needs — a scene id
in, the owning connection's field/value rows out, or ``None`` when unowned —
and the composition root binds the operations-layer implementation once it
exists.

Until bound, every scene resolves as unowned: ``None`` is already the wire
field's own "no change / owner unknown" contract (PY-TS-14), so a send that
races composition needs no special case.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, Self, final, runtime_checkable

if TYPE_CHECKING:
    from punt_lux.domain.ids import SceneId

__all__ = ["FrameOwnerFactsBinding", "FrameOwnerFactsReader", "NoFrameOwnerFacts"]


@runtime_checkable
class FrameOwnerFactsReader(Protocol):
    """Resolves a scene's senior owner into the popup's field/value rows."""

    def facts_for(self, scene_id: SceneId) -> tuple[tuple[str, str], ...] | None:
        """Return the owning connection's rows, or ``None`` if unowned."""
        ...


@final
class NoFrameOwnerFacts:
    """The Null Object: a send before anything bound the real reader."""

    __slots__ = ()

    def facts_for(self, scene_id: SceneId) -> tuple[tuple[str, str], ...] | None:
        """Report every scene as unowned — the honest answer before binding."""
        _ = scene_id  # Null Object: the port's contract, unused by design
        return None


@final
class FrameOwnerFactsBinding:
    """The reader the replicator asks on every send, replaceable at composition."""

    _reader: FrameOwnerFactsReader
    __slots__ = ("_reader",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._reader = NoFrameOwnerFacts()
        return self

    def bind(self, reader: FrameOwnerFactsReader) -> None:
        """Install the reader every later send resolves owner facts through.

        Last binding wins: luxd composes the operations facade at both the
        MCP and REST roots over the same stores, and either may bind.
        """
        self._reader = reader

    def facts_for(self, scene_id: SceneId) -> tuple[tuple[str, str], ...] | None:
        """Delegate to the bound reader (or the Null Object before binding)."""
        return self._reader.facts_for(scene_id)
