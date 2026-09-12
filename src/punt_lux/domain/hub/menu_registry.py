"""HubMenuRegistry — the Hub-owned agent menu bar, keyed by the owning session.

Menus are UI the agent submits, and the Hub is the authority for submitted UI.
This registry holds each session's agent-defined bar as typed models, keyed by the
``ConnectionId`` that registered it, so two sessions never clobber one another's
bar and a departed session's bar leaves the display.

``wire_snapshot`` composes only the *live* sessions' bars, stamping each leaf id
``owner<US>item_id`` so a click round-trips to the session that owns it — the same
read-at-send discipline the Clients menu uses, so a departed owner's bar drops on
the next push whether or not :meth:`drop_session` has pruned it yet. The live read
runs first and outside this registry's lock — the client registry sweeps under
*its* lock — so the two never nest (the ``CallbackRouter`` discipline).

State is guarded by one independent lock, never held across another lock or any
I/O; ``stamped_for``/``to_wire`` build fresh models, so composing under the lock
aliases nothing. The one authoritative instance is built at module scope in
``replicator_instance.py`` and injected at the tools composition root.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.menu_models import Menu

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from punt_lux.domain.hub.callback_ports import LiveSessions
    from punt_lux.domain.ids import ConnectionId

__all__ = ["HubMenuRegistry"]


@final
class HubMenuRegistry:
    """The authoritative agent-defined menu bar, keyed by owning session."""

    _live: LiveSessions
    _lock: threading.Lock
    _by_owner: dict[ConnectionId, tuple[Menu, ...]]
    __slots__ = ("_by_owner", "_live", "_lock")

    def __new__(cls, live: LiveSessions) -> Self:
        self = super().__new__(cls)
        self._live = live
        self._lock = threading.Lock()
        self._by_owner = {}
        return self

    def set_menus(self, connection_id: ConnectionId, menus: Sequence[Menu]) -> None:
        """Replace the bar the session ``connection_id`` owns, leaving others' bars."""
        with self._lock:
            self._by_owner[connection_id] = tuple(menus)

    def drop_session(self, connection_id: ConnectionId) -> None:
        """Prune the session's bar on departure. Idempotent.

        Correctness does not depend on this running: :meth:`wire_snapshot` and
        :meth:`menu_bar` already filter to the live set, so a departed owner's bar
        never renders. This reclaims the entry and lets the next push drop it.
        """
        with self._lock:
            self._by_owner.pop(connection_id, None)

    def menu_bar(self) -> list[Menu]:
        """Return every live session's bar as deep copies (the agent's own view).

        Copied out because ``frozen=True`` does not freeze ``Menu.items`` (a list),
        so a caller cannot reach back through a returned menu and mutate state.
        """
        return [menu.model_copy(deep=True) for _owner, menu in self._live_menus()]

    def wire_snapshot(self) -> tuple[Mapping[str, object], ...]:
        """Return the live sessions' bars as wire payloads, each leaf owner-stamped.

        Read fresh at send time, so the snapshot is the live registry at that
        instant — a departed owner is already gone and a stale menu cannot exist.
        """
        return tuple(
            menu.stamped_for(owner).to_wire() for owner, menu in self._live_menus()
        )

    def _live_menus(self) -> list[tuple[ConnectionId, Menu]]:
        """Return ``(owner, menu)`` for every menu of every live owner, ordered.

        The live-session read runs first and outside this registry's lock, so the
        client registry's lock and this one never nest; owners are ordered so the
        composed bar is stable across reads.
        """
        live = self._live.live_sessions()
        with self._lock:
            owners = sorted(owner for owner in self._by_owner if owner in live)
            return [(owner, menu) for owner in owners for menu in self._by_owner[owner]]
