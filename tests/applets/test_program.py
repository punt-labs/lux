"""AppletProgram — claim the session, serve it, leave with it.

The program serves only if it is the session's applet, and only until its session
goes. These drive the assembly with a watch that ends on cue and a leg that
records whether it was ever serving, so what is asserted is the rule rather than
any timing.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Self, final

from punt_lux.applets.claim import NoClaim, SessionClaim
from punt_lux.applets.program import AppletProgram


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


def test_the_program_serves_until_its_session_ends_and_then_stops() -> None:
    leg = _RecordingLeg()
    program = AppletProgram(NoClaim(), leg, _EndsAfterABeat())  # type: ignore[arg-type]  # structural stand-ins

    asyncio.run(asyncio.wait_for(program.run(), timeout=5))

    assert leg.served  # it did serve
    assert leg.cancelled  # and it was stopped, not left running


def test_a_program_whose_session_is_already_gone_never_starts_serving() -> None:
    """Spawned into a session that has ended: it leaves without taking an entry.

    The watch answers before the leg has run, which is the right order — a menu
    entry for a session nobody is in would be a ghost from the moment it appeared.
    """
    leg = _RecordingLeg()
    program = AppletProgram(NoClaim(), leg, _EndsAtOnce())  # type: ignore[arg-type]  # structural stand-ins

    asyncio.run(asyncio.wait_for(program.run(), timeout=5))

    assert not leg.served


def test_the_program_waits_while_its_session_lives() -> None:
    """Nothing but the session ending takes the entry down."""

    @final
    class _NeverEnds:
        __slots__ = ()

        async def until_session_ends(self) -> None:
            await asyncio.Event().wait()

    leg = _RecordingLeg()
    program = AppletProgram(NoClaim(), leg, _NeverEnds())  # type: ignore[arg-type]  # structural stand-ins

    async def _drive() -> None:
        task = asyncio.create_task(program.run())
        await asyncio.sleep(0.05)
        assert leg.served
        assert not leg.cancelled
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(_drive())


def test_a_second_applet_for_one_session_never_connects(tmp_path: Path) -> None:
    """A hook that fired twice costs the session nothing.

    The second program is refused the claim and leaves without serving, so it
    never registers under the identity the first holds — which is what would have
    taken the first's callbacks and flapped the menu entry. Not serving is the
    whole of it: the leg is what connects and what registers.
    """
    path = tmp_path / "lux-beads-9.pid"
    serving = SessionClaim(path)
    assert serving.take() is True  # this session's applet is already up

    leg = _RecordingLeg()
    program = AppletProgram(SessionClaim(path), leg, _EndsAtOnce())  # type: ignore[arg-type]  # structural stand-ins

    asyncio.run(asyncio.wait_for(program.run(), timeout=5))

    assert not leg.served


def test_the_applet_that_holds_the_claim_serves_normally(tmp_path: Path) -> None:
    """The claim gates the second start, not the first."""
    leg = _RecordingLeg()
    claim = SessionClaim(tmp_path / "lux-beads-10.pid")
    program = AppletProgram(claim, leg, _EndsAfterABeat())  # type: ignore[arg-type]  # structural stand-ins

    asyncio.run(asyncio.wait_for(program.run(), timeout=5))

    assert leg.served
