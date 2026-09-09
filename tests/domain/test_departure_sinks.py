"""DepartureSinks — bind/drop/fire, at most one sink per connection."""

from __future__ import annotations

from punt_lux.domain.hub.departure_sinks import DepartureSink, DepartureSinks
from punt_lux.domain.ids import ConnectionId

_CONN = ConnectionId("sink-conn")


def _recorder() -> tuple[list[ConnectionId], DepartureSink]:
    """A ``DepartureSink`` that appends every connection id it is fired with."""
    seen: list[ConnectionId] = []

    def _sink(connection_id: ConnectionId) -> None:
        seen.append(connection_id)

    return seen, _sink


def test_fire_runs_the_bound_sink_with_the_connection_id() -> None:
    """A bound sink is called with the connection id that departed."""
    sinks = DepartureSinks()
    fired, sink = _recorder()
    sinks.bind(_CONN, sink)

    sinks.fire(_CONN)

    assert fired == [_CONN]


def test_fire_on_an_unbound_connection_is_a_documented_noop() -> None:
    """Most connections have no transport-owned side state -- fire must not raise."""
    sinks = DepartureSinks()

    sinks.fire(ConnectionId("never-bound"))  # must not raise


def test_fire_unbinds_so_a_second_fire_is_a_noop() -> None:
    """Firing consumes the binding -- a departed connection's sink runs once."""
    sinks = DepartureSinks()
    fired, sink = _recorder()
    sinks.bind(_CONN, sink)

    sinks.fire(_CONN)
    sinks.fire(_CONN)

    assert fired == [_CONN]


def test_bind_overwrites_a_prior_sink_for_the_same_connection() -> None:
    """A rebind replaces the sink -- at most one per connection."""
    sinks = DepartureSinks()
    first_fired, first_sink = _recorder()
    second_fired, second_sink = _recorder()
    sinks.bind(_CONN, first_sink)
    sinks.bind(_CONN, second_sink)

    sinks.fire(_CONN)

    assert first_fired == []
    assert second_fired == [_CONN]


def test_drop_unbinds_without_firing() -> None:
    """Drop removes the binding silently -- the sink itself never runs."""
    sinks = DepartureSinks()
    fired, sink = _recorder()
    sinks.bind(_CONN, sink)

    sinks.drop(_CONN)
    sinks.fire(_CONN)

    assert fired == []


def test_drop_on_an_unbound_connection_is_a_noop() -> None:
    """Drop, like fire, must not raise on an id with nothing bound."""
    sinks = DepartureSinks()

    sinks.drop(ConnectionId("never-bound"))  # must not raise


def test_a_bound_function_satisfies_the_departure_sink_protocol() -> None:
    """A plain one-arg callable structurally satisfies DepartureSink."""

    def _sink(connection_id: ConnectionId) -> None:
        del connection_id

    assert isinstance(_sink, DepartureSink)
