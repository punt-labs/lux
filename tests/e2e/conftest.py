"""Fixtures for the business-event-loop harness.

Stands up the in-process rig, points the Hub re-push at it (so the
handler-driven re-push stays hermetic), and hands out simulated agents.
Teardown runs the shipped disconnect cascade for every connection a test
touched — ``hub.on_disconnect`` + ``hub_display.drop_connection`` +
``inbox.drop_session`` — so no scenario leaks subscriptions, writers, or
HubDisplay roots into the next.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

import pytest

from punt_lux.domain.hub import client_registry, hub, hub_display
from punt_lux.domain.ids import ConnectionId
from punt_lux.tools.inbox import drop_session

from .agent import SimulatedAgent
from .rig import InProcessLoop, SyncReplicator

if TYPE_CHECKING:
    from collections.abc import Iterator


class LoopHarness:
    """Owns the rig and every agent a test creates, with cascade teardown."""

    _rig: InProcessLoop
    _created: list[ConnectionId]

    def __new__(cls, rig: InProcessLoop) -> Self:
        self = super().__new__(cls)
        self._rig = rig
        self._created = []
        return self

    @property
    def rig(self) -> InProcessLoop:
        """Return the in-process Hub<->Display rig."""
        return self._rig

    def agent(self, connection_id: str) -> SimulatedAgent:
        """Return a simulated agent bound to its own connection."""
        self._created.append(ConnectionId(connection_id))
        return SimulatedAgent(connection_id=connection_id, rig=self._rig)

    def teardown(self) -> None:
        """Run the disconnect cascade for each connection, then close the rig."""
        for connection_id in self._created:
            hub.on_disconnect(connection_id)
            hub_display.drop_connection(connection_id)
            drop_session(connection_id)
        self._rig.close()


@pytest.fixture
def loop_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[LoopHarness]:
    """Yield a started harness; a click's re-push resolves to the rig's replica."""
    rig = InProcessLoop.start()
    monkeypatch.setattr(client_registry, "get", lambda: rig.repush_client)
    # A click marks the scene dirty; the sync replicator re-pushes it at once,
    # standing in for the background worker so the loop stays deterministic. Patch
    # every name the singleton is bound under: the composition root, and
    # ``tools.tools``, which imports it by name at module load — patching only the
    # root would leave a tool marking the real background replicator.
    sync = SyncReplicator(rig)
    monkeypatch.setattr("punt_lux.domain.hub.replicator_instance.hub_replicator", sync)
    monkeypatch.setattr("punt_lux.tools.tools.hub_replicator", sync)
    harness = LoopHarness(rig)
    yield harness
    harness.teardown()
