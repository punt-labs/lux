"""Applets — small session-bound programs that put an entry in the Lux menu.

An applet is a program, not a daemon and not part of luxd. It runs for the life
of one Claude Code session, in that session's repository and shell, holding the
Lux client's two legs: the WebSocket its clicks arrive on and the REST calls its
work pushes. Everything luxd cannot do itself lives here — launchd starts luxd
with no ``PATH``, no repository and no credentials, so it can no more run ``bd``
than read the user's mail.

They are for software Punt Labs did not build. Beads is the first; the shape is
the same for anything else with a command-line front door.

One module each: an :class:`AppletIdentity` to be known by, a
:class:`SessionClaim` on the session, an :class:`AppletLeg` to serve it on, a
:class:`SessionWatch` that ends it, and :class:`AppletProgram`, which runs them.
"""

from __future__ import annotations

from punt_lux.applets.claim import SessionClaim
from punt_lux.applets.identity import AppletIdentity
from punt_lux.applets.latency import ClickLatency
from punt_lux.applets.leg import AppletLeg
from punt_lux.applets.program import AppletProgram
from punt_lux.applets.service import AppletService
from punt_lux.applets.watch import SessionWatch

__all__ = [
    "AppletIdentity",
    "AppletLeg",
    "AppletProgram",
    "AppletService",
    "ClickLatency",
    "SessionClaim",
    "SessionWatch",
]
