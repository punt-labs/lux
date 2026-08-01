"""The Beads applet: one program, one session, one entry in the Lux menu.

``lux-beads`` is started by the plugin's session-start hook and runs for the life
of that Claude Code session. It exists because luxd cannot do this itself: launchd
starts luxd with no ``PATH``, no repository working directory, and no repository
credentials, while the session has all three. So the session's own program owns
the entry, loads the issues from the session's shell, and pushes the board.

Two things run on its loop and the second decides its life:

- the leg, which registers the entry on connect and services every click;
- the watch, which returns when the session's process is gone.

When the watch returns the leg is cancelled and the process exits. Nothing else
ends it, and nothing else needs to: the socket drops with the process, and the
Hub sweeps the entry with the session's lease whether or not the exit was clean.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Self, final

import typer

from punt_lux.applets.beads_service import BeadsService
from punt_lux.applets.identity import AppletIdentity
from punt_lux.applets.leg import AppletLeg
from punt_lux.applets.watch import NoSession, SessionEnd, SessionWatch
from punt_lux.log_level import level_from_env

logger = logging.getLogger(__name__)

__all__ = ["BeadsApplet", "app"]

app = typer.Typer(
    name="lux-beads",
    help="The Beads applet: this session's board, one click away.",
    add_completion=False,
)


@final
class BeadsApplet:
    """The Beads applet's two concurrent jobs, and the one that ends it."""

    _leg: AppletLeg
    _watch: SessionEnd
    __slots__ = ("_leg", "_watch")

    def __new__(cls, leg: AppletLeg, watch: SessionEnd) -> Self:
        self = super().__new__(cls)
        self._leg = leg
        self._watch = watch
        return self

    @classmethod
    def for_session(cls, session_pid: int) -> Self:
        """Assemble the applet for the session that spawned it, and bound to it."""
        return cls(cls._leg_for(session_pid), SessionWatch(session_pid))

    @classmethod
    def unattended(cls) -> Self:
        """Assemble the applet with nothing to outlive: a hand-run invocation.

        It names itself after its own process, because there is no session to
        name it after, and nothing but its terminal will end it.
        """
        return cls(cls._leg_for(os.getpid()), NoSession())

    @staticmethod
    def _leg_for(session_pid: int) -> AppletLeg:
        """The leg this applet serves on, identified to the Hub by its session."""
        identity = AppletIdentity.for_session(session_pid)
        return AppletLeg(identity.client, BeadsService.for_repo())

    async def run(self) -> None:
        """Serve the entry until the session ends, then stop serving.

        The leg has no terminal state of its own — it reconnects through every
        failure it can — so ending it is a cancellation, not a request. Awaiting
        the cancelled task before returning means the process leaves with its
        teardown run rather than mid-write.
        """
        leg = asyncio.create_task(self._leg.serve())
        try:
            await self._watch.until_session_ends()
        finally:
            leg.cancel()
            await asyncio.gather(leg, return_exceptions=True)


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
