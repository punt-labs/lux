"""One invocation of ``bd``, timed on lux's side of the process boundary.

``subprocess.run`` would do this in a single call, but it bundles the two things
worth telling apart: how long lux took to start the process, and how long ``bd``
then took to answer. ``Popen`` separates them, so a slow board says whether the
slowness was ours.

``bd``'s own wall time stays one figure. What happens inside it is not ours to
instrument, and guessing at it would be worse than reporting it honestly as the
one number lux can actually measure.
"""

from __future__ import annotations

import subprocess
import time
from enum import Enum
from typing import Self, final

from punt_lux.apps.beads_result import BeadsFailure

__all__ = ["BdOutput", "BdRun", "BoardScope"]

# How long a board load waits on ``bd`` before giving up on it. A hosted
# database can be slow; a board that never arrives is worse than a late one.
_BD_TIMEOUT_SECONDS = 60

# How much of ``bd``'s complaint to carry into the message the user reads.
_STDERR_LIMIT = 200


@final
class BoardScope(Enum):
    """Which beads the board shows — the query scope the loader owns.

    ``ACTIVE``, the default, selects by stored status: every ``open`` issue
    plus whatever is ``in_progress``. Selecting by status rather than
    dependency-readiness keeps claimed beads visible once they flip to
    ``in_progress`` and surfaces open-but-blocked issues too. ``ALL`` shows all.
    """

    ACTIVE = ("list", "--json", "--status", "open,in_progress")
    ALL = ("list", "--json", "--all")

    @classmethod
    def for_board(cls, *, all_issues: bool) -> BoardScope:
        """Return the scope a board load asks for."""
        return cls.ALL if all_issues else cls.ACTIVE

    def argv(self) -> list[str]:
        """Return the full ``bd`` command line that selects this scope."""
        return ["bd", *self.value]


@final
class BdOutput:
    """What one ``bd`` run produced: its stdout, and lux's clock around it."""

    _bd_ms: float
    _spawn_ms: float
    _text: str
    __slots__ = ("_bd_ms", "_spawn_ms", "_text")

    def __new__(cls, text: str, spawn_ms: float, bd_ms: float) -> Self:
        self = super().__new__(cls)
        self._text = text
        self._spawn_ms = spawn_ms
        self._bd_ms = bd_ms
        return self

    @classmethod
    def none(cls) -> Self:
        """The output of a run that produced none: nothing read, nothing to time."""
        return cls("", 0.0, 0.0)

    @property
    def text(self) -> str:
        """Everything ``bd`` wrote, as it was written."""
        return self._text

    @property
    def spawn_ms(self) -> float:
        """How long lux took to start the process."""
        return self._spawn_ms

    @property
    def bd_ms(self) -> float:
        """How long lux then waited on ``bd`` to answer."""
        return self._bd_ms

    @property
    def byte_count(self) -> int:
        """How much came back through the pipe, in bytes on the wire."""
        return len(self._text.encode())


@final
class BdRun:
    """Run ``bd`` for a scope, timing the spawn and the wait separately."""

    __slots__ = ()

    def completed(self, scope: BoardScope) -> BdOutput | BeadsFailure:
        """Return what ``bd`` wrote for ``scope``, or the reason it wrote nothing.

        A failure — the command missing, a timeout, a non-zero exit, no output at
        all — comes back as the reason to show rather than as an empty board, so
        the caller can tell "nothing open" from "bd did not run".
        """
        cmd = scope.argv()
        cmd_str = " ".join(cmd)
        spawning = time.perf_counter()
        try:
            process = subprocess.Popen(  # noqa: S603
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError as exc:
            return BeadsFailure(f"{cmd_str}: {exc}")
        spawn_ms = self._since(spawning)
        waiting = time.perf_counter()
        try:
            stdout, stderr = process.communicate(timeout=_BD_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            self._abandon(process)
            return BeadsFailure(f"{cmd_str}: timed out after {_BD_TIMEOUT_SECONDS}s")
        bd_ms = self._since(waiting)
        if process.returncode != 0:
            err = stderr.strip()[:_STDERR_LIMIT] or f"exit {process.returncode}"
            return BeadsFailure(f"{cmd_str}: {err}")
        if not stdout.strip():
            return BeadsFailure(f"{cmd_str}: no output")
        return BdOutput(stdout, spawn_ms, bd_ms)

    @staticmethod
    def _abandon(process: subprocess.Popen[str]) -> None:
        """End a ``bd`` that overran its time and reap it, leaving no zombie."""
        process.kill()
        process.communicate()

    @staticmethod
    def _since(began: float) -> float:
        """Milliseconds since a mark taken off the same clock."""
        return (time.perf_counter() - began) * 1000.0
