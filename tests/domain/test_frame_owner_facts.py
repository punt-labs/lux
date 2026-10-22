"""FrameOwnerFactsBinding — how the replicator resolves a frame's owner facts.

The scene-send path is domain code and may not call the operations layer, so
the composition root binds the real reader. Before it does, the binding holds
the Null Object: every frame resolves as unowned.
"""

from __future__ import annotations

from typing import Self, final

from punt_lux.domain.hub.frame_owner_facts import (
    FrameOwnerFactsBinding,
    FrameOwnerFactsReader,
    NoFrameOwnerFacts,
)
from punt_lux.domain.hub.frame_ownership import FrameOwnership


@final
class _Reader:
    """A reader returning a fixed ownership for one frame id, unowned otherwise."""

    _owned: dict[str, FrameOwnership]
    __slots__ = ("_owned",)

    def __new__(cls, owned: dict[str, FrameOwnership]) -> Self:
        self = super().__new__(cls)
        self._owned = owned
        return self

    def facts_for_frame(self, frame_id: str) -> FrameOwnership:
        return self._owned.get(frame_id, FrameOwnership())


def test_a_bound_reader_answers_the_query() -> None:
    binding = FrameOwnerFactsBinding()
    binding.bind(_Reader({"s1": FrameOwnership((("Client", "lux"),), "lux")}))

    assert binding.facts_for_frame("s1") == FrameOwnership((("Client", "lux"),), "lux")


def test_the_last_binding_wins() -> None:
    """luxd builds a reader at the MCP root and another at REST; either answers."""
    binding = FrameOwnerFactsBinding()
    binding.bind(_Reader({"s1": FrameOwnership((("Client", "first"),), "first")}))
    binding.bind(_Reader({"s1": FrameOwnership((("Client", "second"),), "second")}))

    assert binding.facts_for_frame("s1") == FrameOwnership(
        (("Client", "second"),), "second"
    )


def test_an_unbound_binding_reports_every_frame_unowned() -> None:
    """A send before luxd finished composing itself is unowned, not an error."""
    assert FrameOwnerFactsBinding().facts_for_frame("s1") == FrameOwnership()


def test_the_null_object_reports_unowned() -> None:
    assert NoFrameOwnerFacts().facts_for_frame("s1") == FrameOwnership(None, None)


def test_the_null_object_satisfies_the_reader_contract() -> None:
    assert isinstance(NoFrameOwnerFacts(), FrameOwnerFactsReader)


def test_a_real_reader_satisfies_the_reader_contract() -> None:
    assert isinstance(_Reader({}), FrameOwnerFactsReader)


def test_the_binding_itself_satisfies_the_reader_contract() -> None:
    """The replicator can hold the binding directly as its FrameOwnerFactsReader."""
    assert isinstance(FrameOwnerFactsBinding(), FrameOwnerFactsReader)
