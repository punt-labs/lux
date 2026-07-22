"""HubDisplayConnection — the bounded, never-raising DisplayPort over one socket.

These drive the adapter against a fake client registry so every outcome folds
into a typed ``DisplayReply`` with no socket: a down display, a send failure, a
reconnect that itself fails (``RuntimeError`` from ``connect``), a defective
pong, and the clean paths.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Self, cast

from punt_lux.operations.display_connection import HubDisplayConnection
from punt_lux.operations.display_reply import (
    DisplayErrored,
    DisplayFault,
    DisplayReplied,
)

if TYPE_CHECKING:
    from punt_lux.domain.hub.clients import ClientRegistry


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
    ping_timeout: float | None

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
    drops: int

    def __new__(
        cls, client: _Client, *, connect_error: Exception | None = None
    ) -> Self:
        self = super().__new__(cls)
        self._client = client
        self._connect_error = connect_error
        self.drops = 0
        return self

    def get(self) -> _Client:
        if self._connect_error is not None:
            raise self._connect_error
        return self._client

    def drop(self) -> None:
        self.drops += 1


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
    assert registry.drops == 1


def test_query_maps_a_failed_reconnect_to_unavailable_and_drops() -> None:
    # ClientRegistry.get -> DisplayClient.connect raises RuntimeError when the
    # display dies between the liveness check and the get; it must fold into a
    # typed display_unavailable, not escape as an untyped tool exception.
    registry = _Registry(_Client(), connect_error=RuntimeError("Cannot connect"))
    reply = _conn(registry).query("get_theme", {})
    assert isinstance(reply, DisplayFault)
    assert reply.code == "display_unavailable"
    assert registry.drops == 1


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


def test_ping_maps_a_failed_reconnect_to_unavailable() -> None:
    registry = _Registry(_Client(), connect_error=RuntimeError("Cannot connect"))
    reply = _conn(registry).ping(None)
    assert isinstance(reply, DisplayFault)
    assert reply.code == "display_unavailable"
    assert registry.drops == 1
