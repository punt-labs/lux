"""The one shell the Terminal menu entry started, from its start to its end."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Self, cast

from punt_lux.pty.daemon_exchange import DaemonExchange, SessionRefusedError
from punt_lux.wire.stream.new_request import NewRequest
from punt_lux.wire.stream.session_requests import KillRequest, ListRequest

logger = logging.getLogger(__name__)


class CurrentShell:
    """Own the daemon session behind the Terminal frame: reuse it, never leak it."""

    _daemon: DaemonExchange
    _session: str

    def __new__(cls, daemon: DaemonExchange) -> Self:
        self = super().__new__(cls)
        self._daemon = daemon
        self._session = ""
        return self

    @classmethod
    def local(cls) -> Self:
        """Hold shells on the daemon the helper was started by."""
        return cls(DaemonExchange.local())

    @property
    def session(self) -> str:
        """The id of the held shell; empty when none is held."""
        return self._session

    def obtain(self) -> str:
        """Return the held shell while it runs, else start one.

        Blocks for a bounded time.

        Raises:
            OSError: The daemon is unreachable, hung up or did not answer in time.
            SessionRefusedError: The daemon refused the request or answered nonsense.
        """
        if not (self._session and self._is_running()):
            self._session = self._start()
        return self._session

    def release(self) -> None:
        """Forget the held shell and end it, so none runs without a scene."""
        shell, self._session = self._session, ""
        try:
            self._daemon.ask(KillRequest(2, shell))
        except (OSError, SessionRefusedError):
            logger.exception("Terminal %s could not be ended", shell)

    def _start(self) -> str:
        reply = self._daemon.ask(NewRequest(2))
        try:
            return str(reply.result["session"])
        except KeyError as error:
            raise SessionRefusedError(
                "luxd-pty answered new without a session"
            ) from error

    def _is_running(self) -> bool:
        listing = self._daemon.ask(ListRequest(2)).result.get("sessions")
        if not isinstance(listing, list):
            raise SessionRefusedError("luxd-pty answered list without sessions")
        entries = cast("list[object]", listing)
        named = (
            cast("Mapping[str, object]", entry)
            for entry in entries
            if isinstance(entry, Mapping)
        )
        return any(
            fields.get("session") == self._session and fields.get("state") == "running"
            for fields in named
        )
