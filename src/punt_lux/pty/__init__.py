"""``luxd-pty``: a per-user process that owns terminal sessions.

The Display attaches to a session over a local socket, receives a snapshot of
the screen, then live bytes, and sends keys back. Shells therefore survive a
Display restart, crash or upgrade (``spikes/terminal/STEP4-PLAN.md``).
"""

from __future__ import annotations
