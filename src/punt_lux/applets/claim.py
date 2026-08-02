"""SessionClaim — the one applet a session gets, and how it says so.

A session's start hook fires more than once for one session: ``/resume`` and
``/clear`` both fire it again against the same process. Every firing would
otherwise start another applet under the same session identity, and one identity
is one Hub connection — so each new applet takes the session's callbacks from the
one before it, the menu entry flaps between them, and the ones that lost keep
reconnecting until the session dies. An applet therefore claims its session
before it serves it, and one that cannot claim it leaves.

The claim is an advisory lock on a file named after the session, not a comparison
of the pid written inside it. Two properties follow, and both are why it is a
lock:

- the kernel drops the lock when the holder dies, however it died, so there is no
  stale claim to recognise and no recycled pid to mistake for a live sibling;
- taking it is one atomic operation, so two applets starting at the same instant
  cannot both find it free.

The pid written inside is for the reader — a person looking in the directory —
and never decides anything.

Two rules keep the lock honest. The file is never unlinked: removing it would let
a third applet create a new file and lock that while a second still held the lock
on the old one, and both would then be serving. And the open file is held for as
long as the claim object is, because closing it releases the lock — so whoever
takes a claim keeps it for the life of the process.
"""

from __future__ import annotations

import fcntl
import logging
import os
import tempfile
from io import TextIOWrapper
from pathlib import Path
from typing import Protocol, Self, final, runtime_checkable

logger = logging.getLogger(__name__)

__all__ = ["AppletClaim", "NoClaim", "SessionClaim"]


@runtime_checkable
class AppletClaim(Protocol):
    """What an applet takes before it serves, and answers to if it may not."""

    def take(self) -> bool:
        """Return whether this process may serve, saying why in the log if not."""
        ...


@final
class NoClaim:
    """Nothing to claim: the applet was run by hand and serves nobody's session.

    The Null Object for the one case with no session behind it. A developer
    running an applet in a terminal is not competing with a second copy of
    themselves, so there is nothing here to arbitrate.
    """

    __slots__ = ()

    def take(self) -> bool:
        """Always yield: no session means no sibling that could be serving it."""
        return True


@final
class SessionClaim:
    """The lock a session's applet holds for as long as it is the one serving."""

    _file: TextIOWrapper
    _path: Path
    __slots__ = ("_file", "_path")

    def __new__(cls, path: Path) -> Self:
        self = super().__new__(cls)
        self._path = path
        # Opened for update rather than truncated, so losing the claim leaves the
        # holder's pid intact for whoever reads it. Not inheritable, or a ``bd``
        # child would hold the claim open after the applet that took it had gone.
        # Not through a symlink either: the directory may be shared with other
        # users, and taking the claim writes to whatever this opens.
        self._file = os.fdopen(
            os.open(
                path,
                os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW,
                0o600,
            ),
            "r+",
        )
        return self

    @classmethod
    def for_session(cls, program: str, session_pid: int) -> Self:
        """Address the claim ``program`` takes on ``session_pid``, beside its log.

        The applet's log is written to the same directory under the same name, so
        the two files a session's applet leaves behind sit together and say the
        same thing about which session they belong to.
        """
        return cls(Path(tempfile.gettempdir()) / f"{program}-{session_pid}.pid")

    def take(self) -> bool:
        """Take the claim unless a live applet holds it, and say which happened.

        A refusal is the ordinary outcome of a hook that fired twice rather than
        a failure, so it is one line and a false: the caller leaves, and the
        applet already serving the session keeps its entry and its callbacks.
        """
        try:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logger.info(
                "an applet is already serving this session (%s is held); leaving",
                self._path,
            )
            return False
        self._record()
        return True

    def _record(self) -> None:
        """Write this process's pid into the claim it has just taken.

        What was there was a dead applet's pid, so it is replaced whole rather
        than appended to. The lock is what arbitrates; this is what a person
        reads.
        """
        self._file.seek(0)
        self._file.truncate()
        self._file.write(f"{os.getpid()}\n")
        self._file.flush()
