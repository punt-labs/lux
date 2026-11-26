"""Resume a viewer on a running session and send it the first snapshot."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self

from punt_lux.pty.snapshot_cut import SnapshotCut
from punt_lux.pty.stream_output import StreamPublisher
from punt_lux.terminal.snapshot import SnapshotError

if TYPE_CHECKING:
    from punt_lux.pty.core import SessionCore
    from punt_lux.pty.peer import Peer
    from punt_lux.pty.session import TerminalSession
    from punt_lux.pty.viewers import ViewerBindings
    from punt_lux.terminal.output import SessionSnapshot
    from punt_lux.wire.stream.attach import AttachRequest

logger = logging.getLogger(__name__)


class SessionAttach:
    """Bind a peer to an existing session; a session is never started here."""

    _core: SessionCore
    _bindings: ViewerBindings

    def __new__(cls, core: SessionCore, bindings: ViewerBindings) -> Self:
        self = super().__new__(cls)
        self._core, self._bindings = core, bindings
        return self

    def execute(self, peer: Peer, request: AttachRequest) -> None:
        """Attach ``peer`` to ``request.session``.

        Raises:
            ValueError: The id names no running session.
            SnapshotError: No snapshot can be cut; the client retries.
        """
        size = (request.cols, request.rows)
        session = self._core.attach(request.session)
        self._fit(session, size)
        snapshot = self._cut(session)
        binding = self._bindings.add(peer, session.name, *size)
        StreamPublisher.attach(
            binding, request.request_id, snapshot, session.describe()
        )

    def _fit(self, session: TerminalSession, size: tuple[int, int]) -> None:
        """Let the first viewer set the session's size; later ones follow it."""
        if not self._bindings.session(session.name):
            session.resize(*size)

    @staticmethod
    def _cut(session: TerminalSession) -> SessionSnapshot:
        try:
            return SnapshotCut(session).cut()
        except SnapshotError:
            # Fail this request only: the connection carries every terminal the
            # Display shows, and the client retries with backoff.
            logger.warning(
                "terminal %s: attach failed, no snapshot can be cut",
                session.name,
                exc_info=True,
            )
            raise
