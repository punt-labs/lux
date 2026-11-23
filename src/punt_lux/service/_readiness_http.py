"""Ordinary HTTP connections bounded by socket and whole-request deadlines."""

from __future__ import annotations

import http.client
import socket
import threading
import time
from contextlib import contextmanager, suppress
from typing import TYPE_CHECKING

from punt_lux.kernel.hub_paths import HubPaths

if TYPE_CHECKING:
    from collections.abc import Generator


def _expire(sock: socket.socket) -> None:
    with suppress(OSError):
        sock.shutdown(socket.SHUT_RDWR)


def _remaining(deadline: float) -> float:
    if (remaining := deadline - time.monotonic()) <= 0:
        raise TimeoutError("Hub Display probe deadline elapsed")
    return remaining


@contextmanager
def open_connection(timeout: float) -> Generator[http.client.HTTPConnection]:
    """Close an ordinary connection at the absolute deadline, even during reads."""
    deadline = time.monotonic() + timeout
    if (port := HubPaths().read_port()) is None:
        raise ConnectionError("Hub port file is missing; Hub is not running")
    connection = http.client.HTTPConnection(
        "127.0.0.1", port, timeout=_remaining(deadline)
    )
    watchdog = None
    try:
        connection.connect()
        sock = connection.sock
        if sock is None:
            raise ConnectionError("Hub connection has no socket")
        sock.settimeout(_remaining(deadline))
        watchdog = threading.Timer(_remaining(deadline), _expire, args=(sock,))
        watchdog.daemon = True
        watchdog.start()
        yield connection
    except TimeoutError:
        raise
    except (OSError, http.client.HTTPException, ValueError) as error:
        raise ConnectionError(f"Hub Display probe unavailable: {error}") from error
    finally:
        if watchdog is not None:
            watchdog.cancel()
            watchdog.join()
        connection.close()
