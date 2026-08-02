"""SocketOwner — who owns a Unix socket, according to the operating system.

The one honest answer to "which process is behind this socket" is the kernel's
peer credential: a PID file can be stale, divergent, or written by a process that
has since died, while the credential is read from the live connection itself. So
the socket wins on identity, and this class is how that is asked.

Asking is retried. A live owner whose accept backlog is momentarily full can
refuse or stall a single connect, and concluding "no owner" from one such failure
inverts the truth — the caller would decline to signal a process that is plainly
there, or unlink the socket out from under it. The liveness probe already reads an
ambiguous connect as a live owner; this read must not disagree with it about what
a hiccup means.
"""

from __future__ import annotations

import socket
import sys
import time
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["SocketOwner"]

# connect() timeout — generous, since a live-but-overloaded owner's accept can lag.
_CONNECT_TIMEOUT = 1.0

# How many times to ask before calling the owner unresolvable, and how long to
# wait between asks. Three tries spread over a fifth of a second outlast a
# momentary backlog without adding a wait anyone would notice, since the first
# try succeeds whenever the owner is not saturated.
_ATTEMPTS = 3
_RETRY_SECONDS = 0.1

# Peer-credential socket options by platform: (level, optname, buflen).
# macOS LOCAL_PEERPID (SOL_LOCAL=0) and Linux SO_PEERCRED (SOL_SOCKET=1) both
# carry the owning PID in the first 4 bytes. Raw values sidestep the socket
# module's platform-guarded symbols, keeping the query reachable everywhere.
_PEER_PID_OPT: dict[str, tuple[int, int, int]] = {
    "darwin": (0, 0x002, 4),
    "linux": (1, 17, 12),
}


@final
class SocketOwner:
    """The process behind a Unix socket, read from its OS peer credential."""

    _path: Path
    __slots__ = ("_path",)

    def __new__(cls, path: Path) -> Self:
        self = super().__new__(cls)
        self._path = path
        return self

    def pid(self) -> int | None:
        """Return the owning PID, or ``None`` when no owner can be resolved.

        ``None`` is a genuine absence with three causes, all of which the caller
        must handle the same way — by not signalling anything: nothing listens, the
        platform exposes no peer credential, or every attempt to read it failed.
        A non-positive PID is folded into it too, since the signal path must never
        os.kill a process group.
        """
        opt = _PEER_PID_OPT.get(sys.platform)
        if opt is None:
            return None
        for attempt in range(_ATTEMPTS):
            pid = self._read(opt)
            if pid is not None:
                return pid
            if attempt + 1 < _ATTEMPTS:
                time.sleep(_RETRY_SECONDS)
        return None

    def _read(self, opt: tuple[int, int, int]) -> int | None:
        """One attempt at the peer credential; ``None`` when this attempt failed."""
        level, optname, size = opt
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(_CONNECT_TIMEOUT)
            try:
                probe.connect(str(self._path))
                cred = probe.getsockopt(level, optname, size)
            except OSError:
                return None
            pid = int.from_bytes(cred[:4], sys.byteorder)
            return pid if pid > 0 else None
