"""ProgrammerError -- a defect in the code, never a condition to log and carry on.

A fan-out boundary (a handler list, an interaction route) logs what one bad subscriber
raises so the others still run. That is right for a subscriber's own failure and wrong
for a rule the code broke: a lock taken in the wrong order or a handler fired without
the lock it needs is a bug to see at once, so it passes through every such boundary.
"""

from __future__ import annotations

__all__ = ["ProgrammerError"]


class ProgrammerError(RuntimeError):
    """The code broke a rule it keeps; no fan-out boundary may swallow it."""
