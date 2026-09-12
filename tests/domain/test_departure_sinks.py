"""DepartureSinks — bind/drop/fire, one or more sinks per connection.

A connection may hold more than one piece of transport-owned side state (an MCP
session binds both its inbox queue and, once it owns a menu bar, its
menu-registry prune), so each connection carries a list of sinks, fired in bind
order, with each distinct sink bound at most once.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from punt_lux.domain.hub.departure_sinks import DepartureSink, DepartureSinks
from punt_lux.domain.ids import ConnectionId

if TYPE_CHECKING:
    import pytest

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


def test_fire_runs_every_distinct_sink_in_bind_order() -> None:
    """D2: a connection carries more than one sink -- inbox AND menu prune both fire.

    The pre-fix single-sink store overwrote the inbox sink when the menu prune was
    bound, so a departure released only the second. Both must run, in bind order.
    """
    sinks = DepartureSinks()
    order: list[str] = []

    def _first(connection_id: ConnectionId) -> None:
        del connection_id
        order.append("first")

    def _second(connection_id: ConnectionId) -> None:
        del connection_id
        order.append("second")

    sinks.bind(_CONN, _first)
    sinks.bind(_CONN, _second)

    sinks.fire(_CONN)

    assert order == ["first", "second"]


def test_binding_the_same_sink_twice_fires_it_once() -> None:
    """Re-arming on each menu_set (or reconnect) is idempotent per sink."""
    sinks = DepartureSinks()
    fired, sink = _recorder()
    sinks.bind(_CONN, sink)
    sinks.bind(_CONN, sink)

    sinks.fire(_CONN)

    assert fired == [_CONN]


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


def test_fire_isolates_a_raising_sink_so_the_rest_still_run(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """F2: one sink raising does not starve the others, and the failure is logged.

    Departure is best-effort teardown: with two sinks (inbox cleanup + menu-registry
    prune) bound, a fault in the first must not skip the second. Fail-on-current:
    the pre-fix loop let the first sink's exception abort ``fire`` mid-loop, so the
    second never ran.
    """
    sinks = DepartureSinks()
    second_fired, second_sink = _recorder()

    def _raising(connection_id: ConnectionId) -> None:
        del connection_id
        raise RuntimeError("inbox cleanup blew up")

    sinks.bind(_CONN, _raising)
    sinks.bind(_CONN, second_sink)

    with caplog.at_level(logging.ERROR, logger="punt_lux.domain.hub.departure_sinks"):
        sinks.fire(_CONN)  # must not raise

    assert second_fired == [_CONN]  # the second sink still ran
    assert any("Departure sink failed" in record.message for record in caplog.records)


def test_a_bound_function_satisfies_the_departure_sink_protocol() -> None:
    """A plain one-arg callable structurally satisfies DepartureSink."""

    def _sink(connection_id: ConnectionId) -> None:
        del connection_id

    assert isinstance(_sink, DepartureSink)
