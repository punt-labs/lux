"""ListenerSlot — a connection's listener and the callbacks that listener owns.

One connection is shared by successive sessions of one identity: an old session
dying and a new one reconnecting after a backoff address the same slot. The
session occupying the slot is therefore the connection's ownership token, and
every write to connection-bound state is a compare against it.

The listener and the callbacks are one value rather than two fields because
every rule about them is a rule about the pair. A callback is delivered by push,
so it may exist only while the listener registering it holds the slot: a new
occupant starts with none, releasing clears both at once, and the constructor
refuses a callback with no listener. That state is unreachable rather than
merely avoided — clicks and registrations arrive on other threads and would read it.

Whether the slot is held is a real state, not a missing value, so callers ask
:meth:`held_by` and read :attr:`callbacks` rather than testing for absence.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.domain.hub.callback_ports import CallbackListener
    from punt_lux.domain.hub.session_callback import SessionCallback

__all__ = ["ListenerSlot"]


@final
class ListenerSlot:
    """The connection's current listener, and the callbacks registered against it."""

    # None is the unoccupied slot — a named state, not an absent value (PY-TS-14).
    _listener: CallbackListener | None
    _callbacks: Mapping[str, SessionCallback]
    __slots__ = ("_callbacks", "_listener")

    def __new__(
        cls,
        listener: CallbackListener | None = None,
        callbacks: Mapping[str, SessionCallback] = MappingProxyType({}),
    ) -> Self:
        if listener is None and callbacks:
            msg = "an unheld slot owns no callbacks: a callback needs its listener"
            raise ValueError(msg)
        self = super().__new__(cls)
        self._listener = listener
        self._callbacks = callbacks
        return self

    @property
    def listener(self) -> CallbackListener | None:
        """Who to wake when a click is routed here, or ``None`` if nobody holds it.

        The router reads this from a snapshot taken before its own lock, so it may
        get one that has gone; waking a departed listener is harmless — the click
        is held either way.
        """
        return self._listener

    @property
    def is_held(self) -> bool:
        """Whether a listen leg occupies this slot — the registration gate's read."""
        return self._listener is not None

    @property
    def callbacks(self) -> tuple[SessionCallback, ...]:
        """The callbacks the occupant registered, in registration order."""
        return tuple(self._callbacks.values())

    def held_by(self, listener: CallbackListener) -> bool:
        """Whether ``listener`` is the occupant, compared by object identity.

        Identity is the whole ownership test. A listen session is constructed once
        per run of the route that serves it and installs itself once, so its
        identity is a stamp no later incarnation can reuse. A token that can recur
        — the connection id, or a bare "I installed something" flag — would let a
        superseded session compare equal to its successor and remove its state.
        """
        return self._listener is listener

    def occupied_by(self, listener: CallbackListener) -> ListenerSlot:
        """Return the slot held by ``listener`` and owning no callbacks.

        The new occupant starts empty: those callbacks belonged to whoever held the
        slot and nothing else would withdraw them; the app re-registers on connect.
        """
        return ListenerSlot(listener)

    def released(self) -> ListenerSlot:
        """Return the empty slot — the listener and its callbacks go together."""
        return ListenerSlot()

    def owns(self, callback_id: str) -> bool:
        """Whether the occupant registered a callback under ``callback_id``."""
        return callback_id in self._callbacks

    def with_callback(self, callback: SessionCallback) -> ListenerSlot:
        """Return the slot also owning ``callback``, replacing any entry of its id."""
        return ListenerSlot(self._listener, {**self._callbacks, callback.id: callback})
