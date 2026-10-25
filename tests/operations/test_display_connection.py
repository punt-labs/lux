"""HubDisplayConnection — the bounded, never-raising DisplayPort over one socket.

These drive the adapter against a fake client registry so every outcome folds
into a typed ``DisplayReply`` with no socket: a down display, a send failure, a
reconnect that itself fails (``RuntimeError`` from ``connect``), a defective
pong, and the clean paths.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Self, cast

import pytest

from punt_lux.domain.hub.connection_closed import ConnectionClosedError
from punt_lux.domain.hub.display_busy import DisplayBusyError
from punt_lux.domain.hub.display_not_connected import DisplayNotConnectedError
from punt_lux.operations.display_connection import HubDisplayConnection
from punt_lux.operations.display_reply import (
    DisplayErrored,
    DisplayFault,
    DisplayReplied,
)
from tests.dial_double import fake_dial

if TYPE_CHECKING:
    from punt_lux.domain.hub.clients import ClientRegistry
    from punt_lux.domain.hub.dial_generation import DialGeneration


class _Response:
    _error: str | None
    _result: dict[str, object]

    def __new__(cls, *, error: str | None, result: dict[str, object]) -> Self:
        self = super().__new__(cls)
        self._error = error
        self._result = result
        return self

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def result(self) -> dict[str, object]:
        return self._result


class _Pong:
    _ts: float | None

    def __new__(cls, ts: float | None) -> Self:
        self = super().__new__(cls)
        self._ts = ts
        return self

    @property
    def ts(self) -> float | None:
        return self._ts


class _Client:
    """A display client whose query/ping return a preset value or raise.

    ``ping_delay`` sleeps before the pong returns so a test can prove the
    connection's own clock brackets the round trip.
    """

    _query_reply: object
    _ping_reply: object
    _raise: Exception | None
    _ping_delay: float
    _dial: DialGeneration
    ping_timeout: float | None

    @property
    def requests(self) -> _Client:
        """The outbound port: this fake is its own."""
        return self

    @property
    def dial(self) -> DialGeneration:
        """The dial a failed request names when it asks for the drop."""
        return self._dial

    def __new__(
        cls,
        *,
        query: object = None,
        ping: object = None,
        error: Exception | None = None,
        ping_delay: float = 0.0,
    ) -> Self:
        self = super().__new__(cls)
        self._query_reply = query
        self._ping_reply = ping
        self._raise = error
        self._ping_delay = ping_delay
        self.ping_timeout = None
        self._dial = fake_dial()
        return self

    def query(self, method: str, params: dict[str, object]) -> object:
        if self._raise is not None:
            raise self._raise
        return self._query_reply

    def ping(self, timeout: float | None = None) -> object:
        self.ping_timeout = timeout
        if self._raise is not None:
            raise self._raise
        if self._ping_delay:
            time.sleep(self._ping_delay)
        return self._ping_reply


class _Registry:
    """A client registry that hands out a client (or raises on connect) and drops."""

    _client: _Client
    _connect_error: Exception | None
    is_connected: bool
    drops: list[DialGeneration]

    def __new__(
        cls,
        client: _Client,
        *,
        connect_error: Exception | None = None,
        is_connected: bool = False,
    ) -> Self:
        self = super().__new__(cls)
        self._client = client
        self._connect_error = connect_error
        self.is_connected = is_connected
        self.drops = []
        return self

    @property
    def client_dial(self) -> DialGeneration:
        """The dial the client's requests go out on."""
        return self._client.dial

    def get(self) -> _Client:
        if self._connect_error is not None:
            raise self._connect_error
        return self._client

    def drop(self, generation: DialGeneration) -> None:
        self.drops.append(generation)


def _conn(registry: _Registry, *, running: bool = True) -> HubDisplayConnection:
    # The fake satisfies the registry's get/drop surface structurally; the
    # concrete annotation is bridged with a cast (PY-TS-12).
    return HubDisplayConnection(
        is_running=lambda: running, clients=cast("ClientRegistry", registry)
    )


def test_query_short_circuits_when_the_display_is_not_running() -> None:
    conn = _conn(_Registry(_Client()), running=False)
    reply = conn.query("get_theme", {})
    assert isinstance(reply, DisplayFault)
    assert reply.code == "display_unavailable"


def test_query_maps_a_send_failure_to_timeout_and_drops() -> None:
    registry = _Registry(_Client(error=OSError("EPIPE")))
    reply = _conn(registry).query("get_theme", {})
    assert isinstance(reply, DisplayFault)
    assert reply.code == "timeout"
    assert registry.drops == [registry.client_dial]


def test_query_maps_a_failed_reconnect_to_unavailable_and_drops_nothing() -> None:
    # ClientRegistry.get -> DisplayLink.connect raises RuntimeError when the
    # display dies between the liveness check and the get; it must fold into a
    # typed display_unavailable, not escape as an untyped tool exception.
    registry = _Registry(
        _Client(), connect_error=DisplayNotConnectedError("Cannot connect")
    )
    reply = _conn(registry).query("get_theme", {})
    assert isinstance(reply, DisplayFault)
    assert reply.code == "display_unavailable"
    assert registry.drops == []  # no dial was made, so there is none to drop


def test_query_maps_a_none_reply_to_timeout() -> None:
    reply = _conn(_Registry(_Client(query=None))).query("get_theme", {})
    assert isinstance(reply, DisplayFault)
    assert reply.code == "timeout"


def test_query_maps_a_display_error_reply_to_errored() -> None:
    client = _Client(query=_Response(error="boom", result={}))
    reply = _conn(_Registry(client)).query("get_theme", {})
    assert isinstance(reply, DisplayErrored)
    assert reply.message == "boom"


def test_query_returns_the_payload_on_success() -> None:
    client = _Client(query=_Response(error=None, result={"current": "darcula"}))
    reply = _conn(_Registry(client)).query("get_theme", {})
    assert isinstance(reply, DisplayReplied)
    assert reply.payload == {"current": "darcula"}


def test_ping_measures_the_round_trip_and_is_never_negative() -> None:
    # The connection owns the clock: a client that takes ``delay`` to answer
    # yields an rtt of at least ``delay``. This is a lower bound — machine load
    # can only make the real elapsed larger — so it never flakes, and it can
    # never be negative the way the pre-trip-now subtraction could.
    delay = 0.02
    conn = _conn(_Registry(_Client(ping=_Pong(ts=999.95), ping_delay=delay)))
    reply = conn.ping(None)
    assert isinstance(reply, DisplayReplied)
    rtt = reply.payload["rtt_seconds"]
    assert isinstance(rtt, float)
    assert rtt >= delay


def test_ping_forwards_the_wait_as_the_clients_recv_budget() -> None:
    # The wait is not swallowed at the boundary: it becomes the per-call recv
    # budget on the display client, so --timeout genuinely shortens the wait.
    client = _Client(ping=_Pong(ts=999.95))
    _conn(_Registry(client)).ping(1.5)
    assert client.ping_timeout == 1.5


def test_ping_without_a_timestamp_is_an_error_not_a_zero_rtt() -> None:
    # A pong missing its ts must not read as a perfect 0.0s round-trip.
    reply = _conn(_Registry(_Client(ping=_Pong(ts=None)))).ping(None)
    assert isinstance(reply, DisplayErrored)
    assert reply.message == "pong carried no timestamp"


def test_ping_maps_a_failed_reconnect_to_unavailable_and_drops_nothing() -> None:
    registry = _Registry(
        _Client(), connect_error=DisplayNotConnectedError("Cannot connect")
    )
    reply = _conn(registry).ping(None)
    assert isinstance(reply, DisplayFault)
    assert reply.code == "display_unavailable"
    assert registry.drops == []  # no dial was made, so there is none to drop


def test_is_connected_delegates_to_the_registry() -> None:
    connected = _conn(_Registry(_Client(), is_connected=True))
    disconnected = _conn(_Registry(_Client(), is_connected=False))
    assert connected.is_connected is True
    assert disconnected.is_connected is False


def test_query_maps_a_closed_connection_to_unavailable_and_drops() -> None:
    registry = _Registry(_Client(error=ConnectionClosedError("Not connected")))
    reply = _conn(registry).query("get_theme", {})
    assert isinstance(reply, DisplayFault)
    assert reply.code == "display_unavailable"
    assert registry.drops == [registry.client_dial]


def test_ping_maps_a_closed_connection_to_unavailable_and_drops() -> None:
    registry = _Registry(_Client(error=ConnectionClosedError("listener exited")))
    reply = _conn(registry).ping(None)
    assert isinstance(reply, DisplayFault)
    assert reply.code == "display_unavailable"
    assert registry.drops == [registry.client_dial]


def test_ping_that_lost_the_lock_to_another_ping_is_a_timeout_and_keeps_the_dial() -> (
    None
):
    registry = _Registry(_Client(error=DisplayBusyError("a ping is in flight")))
    reply = _conn(registry).ping(0.1)
    assert isinstance(reply, DisplayFault)
    assert reply.code == "timeout"
    assert registry.drops == []


def test_query_that_lost_the_lock_to_another_query_keeps_the_dial() -> None:
    registry = _Registry(_Client(error=DisplayBusyError("a query is in flight")))
    reply = _conn(registry).query("get_theme", {})
    assert isinstance(reply, DisplayFault)
    assert reply.code == "timeout"
    assert registry.drops == []


@pytest.mark.parametrize("call", ["query", "ping"])
def test_a_runtime_error_that_is_not_a_missing_display_is_not_swallowed(
    call: str,
) -> None:
    # A programming error (say, waiting for a reply on the listener thread)
    # must surface, not read as "no display" and tear the connection down.
    registry = _Registry(_Client(error=RuntimeError("Cannot wait for a reply")))
    conn = _conn(registry)

    with pytest.raises(RuntimeError, match="Cannot wait"):
        conn.query("get_theme", {}) if call == "query" else conn.ping(None)

    assert registry.drops == []
