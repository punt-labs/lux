"""``DisplayNotConnectedError`` -- the display's own dial-failure exception.

Its own module so raising it (:mod:`punt_lux.hub.display_link`) and
catching it (:mod:`punt_lux.hub.replicator`) share one import target
rather than either module owning a type the other merely uses.
"""

from __future__ import annotations

__all__ = ["DisplayNotConnectedError"]


class DisplayNotConnectedError(RuntimeError):
    """Signal that no dial is open and no usable connection could be established.

    Distinct from a plain ``RuntimeError`` raised elsewhere (a mid-send teardown, a
    listener-thread API-misuse guard), so ``HubReplicator`` can pace the "never
    connected" backoff without misclassifying those onto it.
    """
