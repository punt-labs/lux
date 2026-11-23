"""HTTP probes with one deadline across connect, send, headers, and body reads."""

from __future__ import annotations

import http.client
import io
import time
from contextlib import contextmanager
from functools import partial
from typing import TYPE_CHECKING, Self, cast

from punt_lux.kernel.hub_paths import HubPaths

if TYPE_CHECKING:
    import socket
    from collections.abc import Buffer, Generator


class ReadinessHTTP(io.RawIOBase):
    """Adapt HTTPResponse's file reads to a shrinking socket budget."""

    __slots__ = ("_deadline", "_socket")
    _socket: socket.socket
    _deadline: float

    def __new__(cls, sock: socket.socket, deadline: float) -> Self:
        self = super().__new__(cls)
        self._socket, self._deadline = sock, deadline
        return self

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Buffer) -> int:
        self._socket.settimeout(self._remaining(self._deadline))
        return self._socket.recv_into(cast("bytearray", buffer))

    def makefile(self, _mode: str) -> io.BufferedReader:
        """HTTPResponse only asks its socket for a buffered binary reader."""
        return io.BufferedReader(self)

    @staticmethod
    def _response(
        sock: socket.socket,
        debuglevel: int = 0,
        method: str | None = None,
        url: str | None = None,
        *,
        deadline: float,
    ) -> http.client.HTTPResponse:
        reader = ReadinessHTTP(sock, deadline)
        return http.client.HTTPResponse(
            cast("socket.socket", reader), debuglevel=debuglevel, method=method, url=url
        )

    @staticmethod
    def _remaining(deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Hub Display probe deadline elapsed")
        return remaining

    @staticmethod
    @contextmanager
    def open(timeout: float) -> Generator[http.client.HTTPConnection]:
        deadline = time.monotonic() + timeout
        port = HubPaths().read_port()
        if port is None:
            raise ConnectionError(
                "Hub is not running; start it before restarting Display"
            )
        connection = http.client.HTTPConnection(
            "127.0.0.1", port, timeout=ReadinessHTTP._remaining(deadline)
        )
        try:
            connection.connect()
            if connection.sock is None:
                raise ConnectionError("Hub connection closed before the probe")
            connection.sock.settimeout(ReadinessHTTP._remaining(deadline))
            connection.response_class = cast(
                "type[http.client.HTTPResponse]",
                partial(ReadinessHTTP._response, deadline=deadline),
            )
            yield connection
        except TimeoutError:
            raise
        except (OSError, http.client.HTTPException, ValueError) as error:
            raise ConnectionError(f"Hub Display probe unavailable: {error}") from error
        finally:
            connection.close()
