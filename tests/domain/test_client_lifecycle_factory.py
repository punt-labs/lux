"""Tests for ClientLifecycleFactory -- the lifecycle arrives wired and working."""

from __future__ import annotations

from punt_lux.domain.hub.client_lifecycle_factory import ClientLifecycleFactory
from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.owner_tracker import OwnerTracker
from punt_lux.domain.hub.store_lock import StoreLock
from punt_lux.domain.ids import ConnectionId

_CONN = ConnectionId("c1")


class TestClientLifecycleFactory:
    def test_an_arrival_lands_in_the_registry_the_factory_exposes(self) -> None:
        factory = ClientLifecycleFactory(Hub(), lambda: 0.0)
        factory.build(OwnerTracker(), StoreLock()).arrive(_CONN)
        assert factory.registry.session_of(_CONN) is not None

    def test_a_departure_empties_that_registry(self) -> None:
        factory = ClientLifecycleFactory(Hub(), lambda: 0.0)
        lifecycle = factory.build(OwnerTracker(), StoreLock())
        lifecycle.arrive(_CONN)
        lifecycle.depart(_CONN)
        assert factory.registry.session_of(_CONN) is None

    def test_each_factory_owns_a_separate_registry(self) -> None:
        first = ClientLifecycleFactory(Hub(), lambda: 0.0)
        second = ClientLifecycleFactory(Hub(), lambda: 0.0)
        first.build(OwnerTracker(), StoreLock()).arrive(_CONN)
        assert second.registry.session_of(_CONN) is None

    def test_the_factory_clock_drives_the_lease(self) -> None:
        now = [0.0]
        factory = ClientLifecycleFactory(Hub(), lambda: now[0])
        lifecycle = factory.build(OwnerTracker(), StoreLock())
        lifecycle.arrive(_CONN)
        now[0] = 1_000_000.0
        assert lifecycle.depart_lapsed(frozenset()) == frozenset({_CONN})
