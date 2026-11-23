"""AppletProgram — an applet's life: claim the session, serve it, leave with it.

Every applet lives the same three moments and only the middle one is its own.

- It claims its session first. A session gets one applet, and a second one
  starting against a live first would take its callbacks away, so a claim that is
  refused ends the process before it has connected to anything.
- It then serves: the leg registers the entry and answers every click on it.
- It leaves when the session does. The watch is what decides that, and when it
  returns the leg is cancelled and the process is done.

Nothing else ends it, and nothing else needs to: the socket drops with the
process, and the Hub sweeps the entry with the session's lease whether or not the
exit was clean.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.applets.claim import AppletClaim
    from punt_lux.applets.leg import AppletLeg
    from punt_lux.applets.watch import SessionEnd

__all__ = ["AppletProgram"]


@final
class AppletProgram:
    """One applet's three moments: the claim it takes, its leg, and its end."""

    _claim: AppletClaim
    _leg: AppletLeg
    _watch: SessionEnd
    __slots__ = ("_claim", "_leg", "_watch")

    def __new__(cls, claim: AppletClaim, leg: AppletLeg, watch: SessionEnd) -> Self:
        self = super().__new__(cls)
        self._claim = claim
        self._leg = leg
        self._watch = watch
        return self

    async def run(self) -> None:
        """Serve the entry until the session ends, then stop serving.

        A refused claim returns before the leg has run, which is the right order:
        an applet that is not this session's must not so much as connect, because
        connecting under an identity another applet holds is what takes that
        applet's callbacks away.

        The leg has no terminal state of its own — it reconnects through every
        failure it can — so ending it is a cancellation, not a request. Awaiting
        the cancelled task before returning means the process leaves with its
        teardown run rather than mid-write.
        """
        if not self._claim.take():
            return
        leg = asyncio.create_task(self._leg.serve())
        try:
            await self._watch.until_session_ends()
        finally:
            leg.cancel()
            await asyncio.gather(leg, return_exceptions=True)
