"""Snapshot policy: the binary cut when one exists, the visible screen otherwise."""

from __future__ import annotations

import logging
from typing import Protocol, Self

from punt_lux.terminal.output import SessionSnapshot
from punt_lux.terminal.snapshot import ContinuationExhaustedError, SnapshotError
from punt_lux.terminal.snapshot_encoding import SnapshotEncoding

logger = logging.getLogger(__name__)


class Capturable(Protocol):
    """What a cut needs from a session: a name and a capture in an encoding."""

    @property
    def name(self) -> str: ...

    def capture(self, encoding: SnapshotEncoding) -> SessionSnapshot: ...


class SnapshotCut:
    """Cut one session's checkpoint, falling back to the visible screen.

    A program that never reaches parser ground state (a long unterminated OSC
    from tmux, say) exhausts continuation tracking, so waiting for a binary cut
    would starve a viewer for as long as output flows.
    """

    _session: Capturable

    def __new__(cls, session: Capturable) -> Self:
        self = super().__new__(cls)
        self._session = session
        return self

    def cut(self) -> SessionSnapshot:
        """Return a binary snapshot, or a visible-screen repaint if none exists.

        Raises:
            RuntimeError: The session is closed or failed.
            SnapshotError: Neither encoding can be cut; the message carries
                both failures.
        """
        try:
            return self._session.capture(SnapshotEncoding.BINARY)
        except SnapshotError as binary:
            # Continuation exhaustion is the expected reason; anything else is
            # worth a warning because the viewer gets a lossier repaint.
            level = (
                logging.DEBUG
                if isinstance(binary, ContinuationExhaustedError)
                else logging.WARNING
            )
            logger.log(
                level,
                "terminal %s: binary snapshot failed, repainting visible screen: %s",
                self._session.name,
                binary,
            )
            try:
                return self._session.capture(SnapshotEncoding.VT)
            except SnapshotError as visible:
                raise SnapshotError(
                    f"binary: {binary}; visible: {visible}"
                ) from visible
