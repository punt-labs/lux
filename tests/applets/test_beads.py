"""BeadsApplet — two jobs on one loop, and the one that ends the process.

The applet serves until its session goes. These drive the assembly with a watch
that ends on cue and a leg that records whether it was still serving, so what is
asserted is the lifetime rule rather than any timing.
"""

from __future__ import annotations

import asyncio
from typing import Self, final

from punt_lux.applets.beads import BeadsApplet


@final
class _RecordingLeg:
    """A leg that serves until cancelled and remembers that it was."""

    _served: bool
    _cancelled: bool
    __slots__ = ("_cancelled", "_served")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._served = False
        self._cancelled = False
        return self

    async def serve(self) -> None:
        self._served = True
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self._cancelled = True
            raise

    @property
    def served(self) -> bool:
        return self._served

    @property
    def cancelled(self) -> bool:
        return self._cancelled


@final
class _EndsAtOnce:
    """A session that is already over when the applet asks."""

    __slots__ = ()

    async def until_session_ends(self) -> None:
        return


@final
class _EndsAfterABeat:
    """A session that goes while the applet is serving — the ordinary case."""

    __slots__ = ()

    async def until_session_ends(self) -> None:
        await asyncio.sleep(0.02)


def test_the_applet_serves_until_its_session_ends_and_then_stops() -> None:
    leg = _RecordingLeg()
    applet = BeadsApplet(leg, _EndsAfterABeat())  # type: ignore[arg-type]  # structural stand-ins

    asyncio.run(asyncio.wait_for(applet.run(), timeout=5))

    assert leg.served  # it did serve
    assert leg.cancelled  # and it was stopped, not left running


def test_an_applet_whose_session_is_already_gone_never_starts_serving() -> None:
    """Spawned into a session that has ended: it leaves without taking an entry.

    The watch answers before the leg has run, which is the right order — a menu
    entry for a session nobody is in would be a ghost from the moment it appeared.
    """
    leg = _RecordingLeg()
    applet = BeadsApplet(leg, _EndsAtOnce())  # type: ignore[arg-type]  # structural stand-ins

    asyncio.run(asyncio.wait_for(applet.run(), timeout=5))

    assert not leg.served


def test_the_applet_waits_while_its_session_lives() -> None:
    """Nothing but the session ending takes the entry down."""

    @final
    class _NeverEnds:
        __slots__ = ()

        async def until_session_ends(self) -> None:
            await asyncio.Event().wait()

    leg = _RecordingLeg()
    applet = BeadsApplet(leg, _NeverEnds())  # type: ignore[arg-type]  # structural stand-in

    async def _drive() -> None:
        task = asyncio.create_task(applet.run())
        await asyncio.sleep(0.05)
        assert leg.served
        assert not leg.cancelled
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(_drive())
