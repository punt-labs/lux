"""BdChild — one ``bd`` process, owned from its spawn to its reap, and its leash.

A ``bd`` query runs on a worker thread that waits on its child with
``communicate``. A thread cannot be cancelled, so when the work it serves is
cancelled the only way to end the wait is to end the child: ``communicate`` then
returns and the thread with it.

Each call owns its own children. The coroutine that hands a job to a worker thread
makes a :class:`BdLeash` and binds it to its context; ``asyncio.to_thread`` carries
that context into the thread, so the ``bd`` the job starts is attached to the
leash of the call that asked for it, however many layers sit between. Cancelling
that call ends that call's children and nothing else -- there is no registry of
children, and no state that outlives the call.

A child leads its own process group, so ending it ends whatever it started too: a
grandchild that inherited the pipes would otherwise keep ``communicate`` waiting
after ``bd`` itself was gone.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Self, final

from punt_lux.apps.bd_exit import BdCancelledError, BdExit

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

logger = logging.getLogger(__name__)

__all__ = ["BdChild", "BdLeash"]

# How long to wait for a child to be reaped once it has been ended. A killed
# process group answers at once; a child still alive after this is stuck in the
# kernel, and the thread must not wait on it for ever.
_REAP_SECONDS = 5.0


@final
class BdLeash:
    """What lets one call end the ``bd`` children it started, and no one else's."""

    _cancelled: bool
    _children: set[BdChild]
    _lock: threading.Lock
    __slots__ = ("_cancelled", "_children", "_lock")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._cancelled = False
        self._lock = threading.Lock()
        self._children = set()
        return self

    @staticmethod
    def current() -> BdLeash:
        """Return the leash of the call this thread is working for.

        Only a thread started by :meth:`served` -- or by ``asyncio.to_thread``
        inside it -- carries a leash. A thread nobody bound one to (the CLI, a
        test, a thread started by hand) gets a fresh leash that nothing holds, so
        what it starts is never cancelled: it belongs to no call that could be.
        """
        bound = _BOUND.get()
        return BdLeash() if bound is None else bound

    @property
    def cancelled(self) -> bool:
        """Whether the call this leash belongs to has been cancelled."""
        with self._lock:
            return self._cancelled

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
        waits for it before it can exit. So cancellation ends the children this
        call started and the thread returns with them; another call is untouched.
        The job that was waiting on one of them ends with
        :class:`BdCancelledError` -- a ``BaseException``, so no failure boundary
        on the thread reports it -- and nobody awaits that thread any more.
        """
        with self.bound():
            try:
                await asyncio.to_thread(job)
            except asyncio.CancelledError:
                self.cancel()
                raise

    def attach(self, child: BdChild) -> bool:
        """Hold *child* as one of this call's; end it and say no if cancelled."""
        with self._lock:
            if not self._cancelled:
                self._children.add(child)
                return True
        child.end()
        return False

    def detach(self, child: BdChild) -> None:
        """Let go of *child*, which has finished and needs ending by no one."""
        with self._lock:
            self._children.discard(child)

    def cancel(self) -> None:
        """End every child this call has running, and admit no later one."""
        with self._lock:
            self._cancelled = True
            running = tuple(self._children)
        for child in running:
            child.end()


# None is the documented state of a thread with no call behind it.
_BOUND: ContextVar[BdLeash | None] = ContextVar("bd_leash", default=None)


@final
class BdChild:
    """One spawned ``bd`` and the wait on it, held by its call's leash."""

    _argv: tuple[str, ...]
    _leash: BdLeash
    _process: subprocess.Popen[str]
    __slots__ = ("_argv", "_leash", "_process")

    def __new__(cls, argv: list[str], leash: BdLeash) -> Self:
        """Start *argv* under *leash*; raises OSError if it cannot be started."""
        self = super().__new__(cls)
        self._argv = tuple(argv)
        self._leash = leash
        self._process = subprocess.Popen(  # noqa: S603
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        leash.attach(self)
        return self

    @property
    def pid(self) -> int:
        """The process id of the child, which is also its process group's."""
        return self._process.pid

    def end(self) -> None:
        """End the child and everything it started; a child already gone is fine."""
        if self._process.poll() is not None:
            return
        try:
            os.killpg(self._process.pid, signal.SIGKILL)
        except ProcessLookupError:
            # Exited between the check and the signal: the end we wanted.
            return

    def output(self, timeout: float) -> BdExit:
        """Return what the child wrote and how it exited, once it ends.

        On a timeout the child is ended and reaped, leaving no zombie, and
        ``subprocess.TimeoutExpired`` is raised for the caller to word. A child
        ended because its call was cancelled raises :class:`BdCancelledError`
        instead of returning the status of the kill.
        """
        try:
            stdout, stderr = self._process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._reaped()
            raise
        finally:
            self._leash.detach(self)
        if self._leash.cancelled:
            raise BdCancelledError(" ".join(self._argv))
        return BdExit(stdout, stderr, self._process.returncode)

    def _reaped(self) -> None:
        """End the child and wait for it, giving up loudly rather than hanging."""
        self.end()
        try:
            self._process.communicate(timeout=_REAP_SECONDS)
        except subprocess.TimeoutExpired:
            logger.error(
                "bd did not exit after being killed: argv=%s pid=%d",
                " ".join(self._argv),
                self._process.pid,
            )
