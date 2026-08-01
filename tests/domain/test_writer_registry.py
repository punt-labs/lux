"""WriterRegistry — binding, the two ways a writer is dropped, and the raise."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from punt_lux.domain.hub import WriterRegistry
from punt_lux.domain.ids import ConnectionId
from punt_lux.protocol.messages.observer import ObserverMessage

if TYPE_CHECKING:
    from punt_lux.domain.hub import Handler


def _writer() -> tuple[Handler, list[ObserverMessage]]:
    """A writer and the messages it received — distinct objects per call."""
    received: list[ObserverMessage] = []

    def _handler(message: ObserverMessage) -> None:
        received.append(message)

    return _handler, received


_CONN = ConnectionId("c1")


def test_bind_makes_the_writer_the_connections() -> None:
    registry = WriterRegistry()
    writer, _ = _writer()
    assert not registry.has(_CONN)
    registry.bind(_CONN, writer)
    assert registry.has(_CONN)
    assert registry.writer_for(_CONN) is writer


def test_bind_replaces_the_previous_writer() -> None:
    """A reconnect of the same identity takes the connection over."""
    registry = WriterRegistry()
    first, _ = _writer()
    second, _ = _writer()
    registry.bind(_CONN, first)
    registry.bind(_CONN, second)
    assert registry.writer_for(_CONN) is second


def test_drop_unbinds_whoever_holds_it() -> None:
    registry = WriterRegistry()
    writer, _ = _writer()
    registry.bind(_CONN, writer)
    registry.drop(_CONN)
    assert not registry.has(_CONN)
    registry.drop(_CONN)  # idempotent


def test_release_unbinds_only_its_own() -> None:
    """The departing session's withdrawal, and the one it must not perform.

    A session superseded while its socket wound down finds its successor bound
    here. Unbinding regardless would silence a live leg with nothing left to
    rebind it, which is the clobber the ownership rule exists to rule out.
    """
    registry = WriterRegistry()
    departing, _ = _writer()
    successor, _ = _writer()

    registry.bind(_CONN, departing)
    registry.release(_CONN, departing)
    assert not registry.has(_CONN)

    registry.bind(_CONN, successor)
    registry.release(_CONN, departing)
    assert registry.writer_for(_CONN) is successor


def test_release_on_an_unbound_connection_is_a_no_op() -> None:
    registry = WriterRegistry()
    writer, _ = _writer()
    registry.release(_CONN, writer)  # no raise
    assert not registry.has(_CONN)


def test_writer_for_raises_rather_than_answering_with_an_absence() -> None:
    """A subscription against no writer would have no recipient, so this raises."""
    registry = WriterRegistry()
    with pytest.raises(KeyError, match="no writer registered"):
        registry.writer_for(_CONN)
