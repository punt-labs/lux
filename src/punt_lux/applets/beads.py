"""The Beads applet: one program, one session, one entry in the Lux menu.

``lux-beads`` is started by the plugin's session-start hook and runs for the life
of that Claude Code session. It exists because luxd cannot do this itself: launchd
starts luxd with no ``PATH``, no repository working directory, and no repository
credentials, while the session has all three. So the session's own program owns
the entry, loads the issues from the session's shell, and pushes the board.

What it is assembled from is the same for any applet — a claim on the session, a
leg to serve it on, and a watch that ends it — so the living of that life belongs
to :class:`~punt_lux.applets.program.AppletProgram`. What is Beads' own is the
service the leg carries.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Self, final

import typer

from punt_lux.applets.beads_service import BeadsService
from punt_lux.applets.claim import NoClaim, SessionClaim
from punt_lux.applets.identity import AppletIdentity
from punt_lux.applets.leg import AppletLeg
from punt_lux.applets.program import AppletProgram
from punt_lux.applets.watch import NoSession, SessionWatch
from punt_lux.log_level import level_from_env

logger = logging.getLogger(__name__)

__all__ = ["BeadsApplet", "app"]

app = typer.Typer(
    name="lux-beads",
    help="The Beads applet: this session's board, one click away.",
    add_completion=False,
)

# What this program is called wherever a session's files are named after it: its
# console script, its log, and the claim it takes on the session it serves.
_PROGRAM = "lux-beads"


@final
class BeadsApplet:
    """The Beads applet: how it is assembled for a session, and what runs it."""

    _program: AppletProgram
    __slots__ = ("_program",)

    def __new__(cls, program: AppletProgram) -> Self:
        self = super().__new__(cls)
        self._program = program
        return self

    @classmethod
    def for_session(cls, session_pid: int) -> Self:
        """Assemble the applet for the session that spawned it, and bound to it."""
        return cls(
            AppletProgram(
                SessionClaim.for_session(_PROGRAM, session_pid),
                cls._leg_for(session_pid),
                SessionWatch(session_pid),
            )
        )

    @classmethod
    def unattended(cls) -> Self:
        """Assemble the applet with nothing to outlive: a hand-run invocation.

        It names itself after its own process, because there is no session to
        name it after, and nothing but its terminal will end it. There is no
        session to be the sole applet of either, so it claims nothing.
        """
        return cls(AppletProgram(NoClaim(), cls._leg_for(os.getpid()), NoSession()))

    @staticmethod
    def _leg_for(session_pid: int) -> AppletLeg:
        """The leg this applet serves on, identified to the Hub by its session."""
        identity = AppletIdentity.for_session(_PROGRAM, session_pid)
        return AppletLeg(identity.client, BeadsService.for_repo())

    async def run(self) -> None:
        """Run the applet, which is to say run its program."""
        await self._program.run()


@app.command()
def main(
    session_pid: int = typer.Option(
        0,
        "--session-pid",
        help="The Claude Code process to live alongside; 0 runs until killed.",
    ),
) -> None:
    """Run the Beads applet for one session.

    ``--session-pid`` is what ties the applet's life to the session's, and the
    hook that spawns it always passes one. Its absence means a developer running
    the applet by hand in a terminal, where the terminal is the tie.
    """
    logging.basicConfig(
        stream=sys.stderr,
        level=level_from_env("INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    applet = (
        BeadsApplet.for_session(session_pid)
        if session_pid > 0
        else BeadsApplet.unattended()
    )
    asyncio.run(applet.run())


if __name__ == "__main__":
    app()
