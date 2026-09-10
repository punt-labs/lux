"""``DisplayNotConnectedError`` -- the display's own dial-failure exception.

Its own module so raising it (:mod:`punt_lux.domain.hub.display_link`) and
catching it (:mod:`punt_lux.domain.hub.replicator`) share one import target
rather than either module owning a type the other merely uses.
"""

from __future__ import annotations

__all__ = ["DisplayNotConnectedError"]


class DisplayNotConnectedError(RuntimeError):
    """Raised only by the dial path in ``DisplayLink.connect`` -- no display
    has ever connected. Distinct from a plain ``RuntimeError`` raised
    elsewhere (a mid-send teardown, a listener-thread API-misuse guard), so a
    caller like ``HubReplicator`` can pace the "never connected" backoff
    without misclassifying those other conditions onto it."""
