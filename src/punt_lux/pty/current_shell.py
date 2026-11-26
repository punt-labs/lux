"""The one shell the Terminal menu entry started, from its start to its end."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Self, cast

from punt_lux.pty.daemon_exchange import (
    DaemonExchange,
    RetryableRefusalError,
    SessionRefusedError,
)
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

    def resume(self) -> bool:
        """Say whether the held shell still runs; one that does not is forgotten.

        Never starts a shell. Raises what ``obtain`` raises.
        """
        if self._session and not self._is_running():
            self._session = ""
        return bool(self._session)

    def release(self) -> None:
        """End the held shell so none runs without a scene.

        The shell is forgotten once the daemon no longer holds it: ended, or
        refused as unknown. A kill that failed for any other reason keeps it
        held, so the next release retries rather than orphaning a running shell.
        """
        shell = self._session
        if not shell:
            return
        try:
            self._daemon.ask(KillRequest(2, shell))
        except (RetryableRefusalError, OSError):
            logger.exception("Terminal %s could not be ended", shell)
            return
        except SessionRefusedError as error:
            logger.info("Terminal %s is already gone: %s", shell, error)
        self._session = ""

    def _start(self) -> str:
        reply = self._daemon.ask(NewRequest(2))
        session = reply.result.get("session")
        if not isinstance(session, str) or not session:
            raise SessionRefusedError("luxd-pty answered new without a session")
        return session

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
