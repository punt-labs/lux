"""Single-threaded daemon coordinator with lifetime claim and idle shutdown."""

from __future__ import annotations

import os
import select
from contextlib import ExitStack
from pathlib import Path
from typing import Self

from punt_lux.pty.core import SessionCore
from punt_lux.pty.dispatch import SessionDispatch
from punt_lux.pty.peer_book import PeerBook
from punt_lux.terminal.daemon_claim import DaemonClaim
from punt_lux.terminal.local_endpoint import LocalEndpoint


class PtyServer:
    _claim: DaemonClaim
    _endpoint: LocalEndpoint
    _core: SessionCore
    _dispatch: SessionDispatch
    _clients: PeerBook
    _stopping: bool

    def __new__(cls, path: Path, *, idle_timeout: float | None = 30.0) -> Self:
        self = super().__new__(cls)
        path = path.absolute()
        with ExitStack() as unwind:
            self._claim = DaemonClaim(path)
            unwind.callback(self._claim.close)
            self._endpoint = LocalEndpoint(path)
            unwind.callback(self._endpoint.close)
            self._core = SessionCore()
            self._dispatch = SessionDispatch(self._core)
            self._clients = PeerBook(self._dispatch, idle_timeout)
            unwind.pop_all()
        self._stopping = False
        # The menu helper is a client of this daemon and dials where it listens.
        os.environ["LUX_PTY_SOCKET"] = str(path)
        return self

    @property
    def client_count(self) -> int:
        return len(self._clients.readers)

    @property
    def session_count(self) -> int:
        return len(self._core.describe())

    def stop(self) -> None:
        self._stopping = True

    def run(self) -> None:
        try:
            while not self._stopping:
                self.tick()
        finally:
            self.close()

    def tick(self, timeout: float = 0.005) -> bool:
        self._clients.purge()
        listener = self._endpoint.listener
        ready, writable, _ = select.select(
            [listener, *self._clients.readers], self._clients.writers, [], timeout
        )
        if listener in ready:
            self._clients.accept(listener)
        self._clients.service(ready, writable)
        self._dispatch.pump()
        self._stopping |= self._clients.expired(len(self._core.describe()))
        return not self._stopping

    def close(self) -> None:
        self._clients.close()
        self._endpoint.close()
        try:
            self._core.close()
        finally:
            self._claim.close()
