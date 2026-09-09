"""DepartureCascade — the subscriptions/writer/inbox tail of a departure."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from punt_lux.domain.hub.departure_cascade import DepartureCascade
from punt_lux.domain.hub.departure_sinks import DepartureSink
from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.ids import ConnectionId, Topic

if TYPE_CHECKING:
    import pytest

_CONN = ConnectionId("cascade-conn")


def _recorder() -> tuple[list[ConnectionId], DepartureSink]:
    """A ``DepartureSink`` that appends every connection id it is fired with."""
    seen: list[ConnectionId] = []

    def _sink(connection_id: ConnectionId) -> None:
        seen.append(connection_id)

    return seen, _sink


def test_run_drops_subscriptions_and_writer_via_hub() -> None:
    """The cascade's ``run`` leg reaches ``Hub.on_disconnect``, not a copy of it."""
    hub = Hub()
    hub.register_writer(_CONN, lambda _msg: None)
    hub.subscribe(_CONN, Topic("t"))
    cascade = DepartureCascade(hub)

    cascade.run(_CONN)

    assert not hub.has_writer(_CONN)
    assert hub.topics_for(_CONN) == frozenset()


def test_run_fires_the_connections_bound_sink() -> None:
    """The cascade's second leg fires whatever sink was bound for the connection."""
    hub = Hub()
    cascade = DepartureCascade(hub)
    fired, sink = _recorder()
    cascade.bind_sink(_CONN, sink)

    cascade.run(_CONN)

    assert fired == [_CONN]


def test_run_on_a_connection_with_no_side_state_is_a_noop() -> None:
    """A connection that never bound a writer, subs, or a sink is untouched."""
    hub = Hub()
    cascade = DepartureCascade(hub)

    cascade.run(_CONN)  # must not raise

    assert not hub.has_writer(_CONN)


def test_run_all_runs_the_cascade_for_every_connection_in_the_set() -> None:
    """A swept set gets the identical cascade tail, one connection at a time."""
    hub = Hub()
    first = ConnectionId("swept-1")
    second = ConnectionId("swept-2")
    hub.register_writer(first, lambda _msg: None)
    hub.register_writer(second, lambda _msg: None)
    cascade = DepartureCascade(hub)
    fired: list[ConnectionId] = []

    def _sink(connection_id: ConnectionId) -> None:
        fired.append(connection_id)

    cascade.bind_sink(first, _sink)
    cascade.bind_sink(second, _sink)

    cascade.run_all(frozenset({first, second}))

    assert not hub.has_writer(first)
    assert not hub.has_writer(second)
    assert sorted(fired) == sorted([first, second])


def test_run_all_on_an_empty_set_touches_nothing() -> None:
    """Sweeping an empty set is a pure no-op -- the common case, nothing lapsed."""
    hub = Hub()
    cascade = DepartureCascade(hub)

    cascade.run_all(frozenset())  # must not raise


def test_run_still_fires_the_sink_when_on_disconnect_raises() -> None:
    """A raising ``Hub.on_disconnect`` must not stop the sink leg from firing.

    ``connection_id`` has already been irreversibly removed from the
    registry by the time ``run`` fires, so one leg raising must never skip
    the other or surface as an externally visible disconnect failure.
    """

    class _RaisingHub:
        """A structural ``Hub`` fake whose ``on_disconnect`` always raises."""

        def on_disconnect(self, connection_id: ConnectionId) -> None:
            del connection_id
            msg = "on_disconnect exploded"
            raise RuntimeError(msg)

    cascade = DepartureCascade(_RaisingHub())  # type: ignore[arg-type]  # structural fake
    fired, sink = _recorder()
    cascade.bind_sink(_CONN, sink)

    cascade.run(_CONN)  # must not raise

    assert fired == [_CONN]


def test_run_does_not_raise_when_the_sink_raises() -> None:
    """A raising sink must not surface as an externally visible failure."""
    hub = Hub()
    hub.register_writer(_CONN, lambda _msg: None)
    cascade = DepartureCascade(hub)

    def _raising_sink(connection_id: ConnectionId) -> None:
        del connection_id
        msg = "sink exploded"
        raise RuntimeError(msg)

    cascade.bind_sink(_CONN, _raising_sink)

    cascade.run(_CONN)  # must not raise

    assert not hub.has_writer(_CONN)  # the on_disconnect leg still completed


def test_run_all_isolates_a_raising_connections_cascade_from_the_rest(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """One connection's cascade raising must not strand the rest of the sweep.

    The registry-and-ownership removal for the whole set has already run by
    the time ``run_all`` fires; a raise partway through the per-connection
    tail must still let every *other* connection's subscriptions and writer
    binding drop, and must log which connection's cascade failed.
    """
    hub = Hub()
    good_first = ConnectionId("swept-good-first")
    bad = ConnectionId("swept-bad")
    good_last = ConnectionId("swept-good-last")
    for connection_id in (good_first, bad, good_last):
        hub.register_writer(connection_id, lambda _msg: None)
    cascade = DepartureCascade(hub)

    def _raising_sink(connection_id: ConnectionId) -> None:
        msg = f"sink exploded for {connection_id}"
        raise RuntimeError(msg)

    cascade.bind_sink(bad, _raising_sink)

    with caplog.at_level(logging.ERROR):
        cascade.run_all((good_first, bad, good_last))

    assert not hub.has_writer(good_first)
    assert not hub.has_writer(good_last)
    assert str(bad) in caplog.text
