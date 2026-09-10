"""DisconnectedRetry — paces and logs the replicator's never-connected wait.

The one thing HubReplicator's disconnected branch needs, bundled: a backoff
that grows toward a slow, minute-scale cap, a wait that any reconnect can
break early, and a log line that states the condition once per transition
instead of once per cycle (display-presence-demand-driven.md §6.3, §6.5).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol, Self, final, runtime_checkable

from punt_lux.domain.hub.reconnect_wait import ReconnectWait
from punt_lux.domain.hub.respawn_backoff import RespawnBackoff

if TYPE_CHECKING:
    from punt_lux.domain.hub.backoff_config import BackoffConfig

logger = logging.getLogger(__name__)

__all__ = ["DisconnectedRetry", "ReconnectWaiter"]


@runtime_checkable
class ReconnectWaiter(Protocol):
    """The two capabilities ``wait`` needs — narrower than ``ClientProvider``."""

    @property
    def reconnect_generation(self) -> int:
        """Return the current reconnect generation, snapshot before a dial."""
        ...

    def wait_for_reconnect(self, wait: ReconnectWait) -> bool:
        """Block up to ``wait.timeout``s for a reconnect after ``wait.since_gen``."""
        ...


@final
class DisconnectedRetry:
    """Paces the wait when no display has ever connected, logging once per state."""

    _config: BackoffConfig
    _backoff: RespawnBackoff
    _was_disconnected: bool
    __slots__ = ("_backoff", "_config", "_was_disconnected")

    def __new__(cls, config: BackoffConfig) -> Self:
        self = super().__new__(cls)
        self._config = config
        self._backoff = RespawnBackoff(config)
        self._was_disconnected = False
        return self

    @property
    def current_delay(self) -> float:
        """Return the pending retry delay, in seconds (design §9)."""
        return self._backoff.current_delay

    def wait(self, clients: ReconnectWaiter, *, since_gen: int) -> None:
        """Wait the current delay, breakable by a reconnect since ``since_gen``;
        grow it after. The caller snapshots ``since_gen`` BEFORE its own dial
        attempt, so a reconnect racing that attempt is never missed."""
        delay = self._backoff.note_respawn()
        self._log(delay)
        clients.wait_for_reconnect(ReconnectWait(since_gen, delay))

    def _log(self, delay: float) -> None:
        """Log once, at INFO, on the transition; DEBUG on every repeat."""
        if self._was_disconnected:
            logger.debug("display still not connected; retrying in %.1fs", delay)
            return
        logger.info("display not connected; retrying in %.1fs, backing off", delay)
        self._was_disconnected = True

    def reset(self) -> None:
        """Reset to base on a clean SEND, not merely a successful dial -- a
        dial whose immediate send fails is ``recovered``, never routed here."""
        self._backoff = RespawnBackoff(self._config)
        self._was_disconnected = False
