"""ListenerSlot — a connection's listener and the callbacks that listener owns.

One connection is shared by successive sessions of one identity: an old session
dying and a new one reconnecting after a backoff address the same slot. The
session occupying the slot is therefore the connection's ownership token, and
every write to connection-bound state is a compare against it.

The listener and the callbacks are one value rather than two fields because
every rule about them is a rule about the pair. A callback is delivered by push,
so it may exist only while the listener that registered it holds the slot: a new
occupant starts with none, and releasing the slot clears both at once. Splitting
them into two writes leaves a window in which a callback has no listener, and
that window is observable — clicks and registrations arrive on other threads.

Whether the slot is held is a real state, not a missing value, so callers ask
:meth:`held_by` and read :attr:`callbacks` rather than testing for absence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.domain.hub.callback_ports import CallbackListener
    from punt_lux.domain.hub.session_callback import SessionCallback

__all__ = ["ListenerSlot"]


@final
class ListenerSlot:
    """The connection's current listener, and the callbacks registered against it."""

    # None is the unoccupied slot — a connection with no listen leg, which is a
    # state the design has names for, not an absent value (PY-TS-14).
    _listener: CallbackListener | None
    _callbacks: tuple[SessionCallback, ...]
    __slots__ = ("_callbacks", "_listener")

    def __new__(
        cls,
        listener: CallbackListener | None = None,
        callbacks: tuple[SessionCallback, ...] = (),
    ) -> Self:
        self = super().__new__(cls)
        self._listener = listener
        self._callbacks = callbacks
        return self

    @property
    def listener(self) -> CallbackListener | None:
        """Who to wake when a click is routed here, or ``None`` if nobody holds it.

        The router reads this from a snapshot it took before its own lock, so a
        listener it gets back may already have gone; waking a departed one is
        harmless, since the click is buffered either way.
        """
        return self._listener

    @property
    def is_held(self) -> bool:
        """Whether a listen leg occupies this slot — the registration gate's read."""
        return self._listener is not None

    @property
    def callbacks(self) -> tuple[SessionCallback, ...]:
        """The callbacks the occupant registered, in registration order."""
        return self._callbacks

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

        The new occupant starts empty: the callbacks in the slot belonged to whoever
        held it, and nothing else will ever withdraw them. The app re-registers from
        its connect hook, so what it still wants comes back at once.
        """
        return ListenerSlot(listener)

    def released(self) -> ListenerSlot:
        """Return the empty slot — the listener and its callbacks go together."""
        return ListenerSlot()

    def owns(self, callback_id: str) -> bool:
        """Whether the occupant registered a callback under ``callback_id``."""
        return any(callback.id == callback_id for callback in self._callbacks)

    def with_callback(self, callback: SessionCallback) -> ListenerSlot:
        """Return the slot also owning ``callback``, last write winning by id.

        A callback whose id the slot already holds replaces the earlier one, so one
        id never names two entries; a new id is appended.
        """
        kept = tuple(c for c in self._callbacks if c.id != callback.id)
        return ListenerSlot(self._listener, (*kept, callback))
