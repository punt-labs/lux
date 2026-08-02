"""BeadsApplet — the assembly ``lux-beads`` runs, and what running it means.

The life it leads is its program's and is asserted there. What is left here is
that the applet is that program: the entry point runs what it was assembled with
and adds nothing of its own.
"""

from __future__ import annotations

import asyncio
from typing import Self, final

from punt_lux.applets.beads import BeadsApplet


@final
class _RecordingProgram:
    """A program that remembers it was run."""

    _ran: bool
    __slots__ = ("_ran",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._ran = False
        return self

    async def run(self) -> None:
        self._ran = True

    @property
    def ran(self) -> bool:
        return self._ran


def test_running_the_applet_runs_its_program() -> None:
    program = _RecordingProgram()

    asyncio.run(asyncio.wait_for(BeadsApplet(program).run(), timeout=5))  # type: ignore[arg-type]  # structural stand-in

    assert program.ran
