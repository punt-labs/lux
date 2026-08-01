"""Applets — small session-bound programs that put an entry in the Lux menu.

An applet is a program, not a daemon and not part of luxd. It runs for the life
of one Claude Code session, in that session's repository and shell, holding the
Lux client's two legs: the WebSocket its menu clicks arrive on and the REST calls
its work pushes. Everything luxd cannot do itself lives here — luxd is started by
launchd with no ``PATH``, no repository, and no credentials, so it can no more
run ``bd`` than it can read the user's mail.

They are for software Punt Labs did not build. Beads is the first; the shape is
the same for anything else with a command-line front door.

The three parts an applet is assembled from:

- :class:`~punt_lux.applets.identity.AppletIdentity` — who it says it is, which
  is what the user reads in the menu bar and what both legs resolve to one Hub
  connection through;
- :class:`~punt_lux.applets.leg.AppletLeg` — the connection: register on connect,
  service the clicks it pushes, and never let one bad click cost the socket;
- :class:`~punt_lux.applets.watch.SessionWatch` — the promise that it leaves when
  its session does.
"""

from __future__ import annotations

from punt_lux.applets.identity import AppletIdentity
from punt_lux.applets.latency import ClickLatency
from punt_lux.applets.leg import AppletLeg, AppletService
from punt_lux.applets.watch import SessionWatch

__all__ = [
    "AppletIdentity",
    "AppletLeg",
    "AppletService",
    "ClickLatency",
    "SessionWatch",
]
