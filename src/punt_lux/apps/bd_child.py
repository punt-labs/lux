"""BdChild — one ``bd`` process, owned from its spawn to its reap, and its leash.

A ``bd`` query runs on a worker thread that waits on its child with
``communicate``. A thread cannot be cancelled, so when the work it serves is
cancelled the only way to end the wait is to end the child: ``communicate`` then
returns and the thread with it.

Each call owns its own child. The coroutine that hands a job to a worker thread
makes a :class:`BdLeash` and binds it to its context; ``asyncio.to_thread`` carries
that context into the thread, so the ``bd`` the job starts is attached to the
leash of the call that asked for it, however many layers sit between. Cancelling
that call ends that call's child and nothing else -- there is no registry of
children, and no state that outlives the call.
"""

from __future__ import annotations

import asyncio
import subprocess
import threading
from collections.abc import Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Self, final

__all__ = ["BdChild", "BdLeash"]


@final
class BdLeash:
    """What lets one call end the ``bd`` it started, and no one else's."""

    _cancelled: bool
    _lock: threading.Lock
    # None is the documented state of a call with no ``bd`` running right now.
    _child: subprocess.Popen[str] | None
    __slots__ = ("_cancelled", "_child", "_lock")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._cancelled = False
        self._lock = threading.Lock()
        self._child = None
        return self

    @staticmethod
    def current() -> BdLeash:
        """Return the leash of the call this thread is working for.

        A thread nobody bound one to -- the CLI, a test -- gets a fresh leash that
        nothing holds, so it is never cancelled.
        """
        try:
            return _BOUND.get()
        except LookupError:
            return BdLeash()

    @contextmanager
    def bound(self) -> Generator[Self]:
        """Make this the leash of every thread started from the calling context."""
        token = _BOUND.set(self)
        try:
            yield self
        finally:
            _BOUND.reset(token)

    async def served(self, job: Callable[[], None]) -> None:
        """Run *job* on a worker thread as this call; cancelling ends its ``bd``.

        A worker thread cannot be cancelled, only outwaited, and the process
        waits for it before it can exit. So cancellation ends the one child this
        call started and the thread returns with it; another call is untouched.
        """
        with self.bound():
            try:
                await asyncio.to_thread(job)
            except asyncio.CancelledError:
                self.cancel()
                raise

    def attach(self, process: subprocess.Popen[str]) -> bool:
        """Hold *process* as this call's child; end it and say no if cancelled."""
        with self._lock:
            if not self._cancelled:
                self._child = process
                return True
        process.kill()
        return False

    def detach(self) -> None:
        """Let go of the child, which has finished and needs ending by no one."""
        with self._lock:
            self._child = None

    def cancel(self) -> None:
        """End this call's child, if it has one, and admit no later one."""
        with self._lock:
            self._cancelled = True
            child = self._child
        if child is not None:
            child.kill()


_BOUND: ContextVar[BdLeash] = ContextVar("bd_leash")


@final
class BdChild:
    """One spawned ``bd`` and the wait on it, held by its call's leash."""

    _leash: BdLeash
    _process: subprocess.Popen[str]
    __slots__ = ("_leash", "_process")

    def __new__(cls, argv: list[str], leash: BdLeash) -> Self:
        """Start *argv* under *leash*; raises OSError if it cannot be started."""
        self = super().__new__(cls)
        self._leash = leash
        self._process = subprocess.Popen(  # noqa: S603
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        leash.attach(self._process)
        return self

    @property
    def returncode(self) -> int:
        """The exit code, valid once :meth:`output` has returned."""
        return int(self._process.returncode)

    def output(self, timeout: float) -> tuple[str, str]:
        """Return ``(stdout, stderr)`` once the child ends.

        On a timeout the child is ended and reaped, leaving no zombie, and
        ``subprocess.TimeoutExpired`` is raised for the caller to word.
        """
        try:
            return self._process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.communicate()
            raise
        finally:
            self._leash.detach()
