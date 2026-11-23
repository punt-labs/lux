"""Underway — the work a leg starts and does not wait on.

A connection's receive loop reads its next frame only when the handler for the
current one returns, so a handler that waits for the work it asked for holds
every frame behind it. On this leg that is the difference between a menu that
answers and one that looks dead: the click a user makes while their last one is
still loading cannot even be acknowledged until that load has finished. The work
is started here instead, and the handler returns to the frame behind it.

A task nobody holds a reference to may be collected mid-run, so every task
started here is held until it ends. Nothing here reads how one ended: each piece
of work carries its own failure boundary, because a failure escaping this far
would have nowhere left to go but a task nobody reads.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Coroutine

__all__ = ["Underway"]


@final
class Underway:
    """The work a leg has in flight, held so that none of it is collected mid-run."""

    _tasks: set[asyncio.Task[None]]
    __slots__ = ("_tasks",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._tasks = set()
        return self

    def start(self, work: Coroutine[object, object, None]) -> None:
        """Run *work* on this loop, and return to the caller without waiting."""
        task = asyncio.create_task(work)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def drained(self) -> None:
        """Wait for everything started so far, and raise anything one let escape.

        Nothing on a session's leg calls this — the leg has no shutdown, and the
        work is started precisely so that nobody waits on it. It is how a test
        holds the whole of a click, and how it hears about a failure that got
        past the boundary the work was supposed to end in.
        """
        await asyncio.gather(*tuple(self._tasks))
