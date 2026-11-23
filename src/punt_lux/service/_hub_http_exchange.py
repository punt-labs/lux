"""Ordinary HTTP connections bounded by socket and whole-request deadlines."""

from __future__ import annotations

import http.client
from contextlib import contextmanager
from typing import TYPE_CHECKING, Self

from punt_lux.kernel.hub_paths import HubPaths
from punt_lux.service._readiness_http import ProbeDeadline

if TYPE_CHECKING:
    from collections.abc import Generator


class ReadinessHTTP:
    """Own the shared deadline of one ordinary Hub HTTP exchange."""

    _budget: ProbeDeadline

    def __new__(cls, timeout: float) -> Self:
        self = super().__new__(cls)
        self._budget = ProbeDeadline(timeout)
        return self

    @contextmanager
    def open(self) -> Generator[http.client.HTTPConnection]:
        """Close the connection after its complete, deadline-bounded exchange."""
        if (port := HubPaths().read_port()) is None:
            raise ConnectionError("Hub port file is missing; Hub is not running")
        connection = http.client.HTTPConnection(
            "127.0.0.1", port, timeout=self._budget.remaining()
        )
        try:
            connection.connect()
            with self._budget.watch(connection.sock):
                yield connection
        finally:
            connection.close()
