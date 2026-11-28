"""Compose the Beads program and its repository-scoped session lifetime."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Self, final

import typer

from punt_lux.applets.claim import NoClaim, SessionClaim
from punt_lux.applets.identity import AppletIdentity
from punt_lux.applets.leg import AppletLeg
from punt_lux.applets.program import AppletProgram
from punt_lux.applets.watch import NoSession, SessionWatch
from punt_lux.beads.beads_service import BeadsService
from punt_lux.kernel.logging_config import process_diagnostics
from punt_lux.service.repo_activation import Checkout

logger = logging.getLogger(__name__)
_PROGRAM = "lux-beads"


class BeadsProgram:
    @classmethod
    def for_session(cls, session_pid: int, checkout: Checkout) -> AppletProgram:
        process = SessionWatch(session_pid)
        return AppletProgram(
            SessionClaim.for_session(_PROGRAM, session_pid),
            cls._leg_for(session_pid),
            BeadsSessionWatch(process, checkout),
        )

    @classmethod
    def unattended(cls) -> AppletProgram:
        return AppletProgram(NoClaim(), cls._leg_for(os.getpid()), NoSession())

    @staticmethod
    def _leg_for(session_pid: int) -> AppletLeg:
        identity = AppletIdentity.for_session(_PROGRAM, session_pid)
        return AppletLeg(identity.client, BeadsService.for_repo())


@final
class BeadsSessionWatch:
    """End a session applet when either Claude exits or Lux is disabled."""

    _checkout: Checkout
    _process: SessionWatch
    __slots__ = ("_checkout", "_process")

    def __new__(cls, process: SessionWatch, checkout: Checkout) -> Self:
        self = super().__new__(cls)
        self._process = process
        self._checkout = checkout
        return self

    async def until_session_ends(self) -> None:
        while self._process.session_is_alive and self._checkout.state().enabled:
            await asyncio.sleep(5)


@final
class BeadsApplet:
    """The Beads applet: how it is assembled for a session, and what runs it."""

    _program: AppletProgram
    __slots__ = ("_program",)

    def __new__(cls, program: AppletProgram) -> Self:
        self = super().__new__(cls)
        self._program = program
        return self

    async def run(self) -> None:
        """Run the applet, which is to say run its program."""
        await self._program.run()

    @staticmethod
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
        checkout = Checkout.enabled_at(Path.cwd()) if session_pid > 0 else None
        if session_pid > 0 and checkout is None:
            return
        with process_diagnostics("worker", "Beads applet"):
            logger.info("Starting Beads applet (session pid=%d)", session_pid)
            program = (
                BeadsProgram.unattended()
                if checkout is None
                else BeadsProgram.for_session(session_pid, checkout)
            )
            asyncio.run(BeadsApplet(program).run())
            logger.info("Beads applet stopped (session pid=%d)", session_pid)
