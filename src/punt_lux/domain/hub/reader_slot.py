"""ReaderSlot -- the one reader a dial may have at a time, and the door to settle it.

A dial's frame buffer is fed by one reader at once: its listener thread, or one
caller's inline wait. The slot says which, and makes the others wait or wait on the
sink that reader feeds. It is a leaf lock, held only to read or change the holder or
the debt, never while taking another lock or doing I/O; claiming it for a listener waits
out an inline read in flight, so no caller may hold a lock the request model or the
registry shares.

The slot is also the door through which a dial is settled. Only its holder is handed a
:class:`~punt_lux.domain.hub.settler.Settler` (a listener, through its
:class:`ListenerHold`, once), and only the slot makes one. Whoever ends
a dial and is not the holder asks (:meth:`ask_settle`): a free slot is taken and the
dial settled on the spot; a held slot is refused and a *debt* left, in the one critical
section that observed it held. Every release of the slot reads the debt in the one
critical section that frees it, and a debt keeps the slot: the releaser settles the dial
before it lets go. A refused asker waits for the holder, up to
:data:`~punt_lux.domain.hub.bounded_ask.SETTLE_BOUND`, and then settles the dial itself
through the capability the refusal handed it.
"""

from __future__ import annotations

import contextlib
import threading
from typing import TYPE_CHECKING, Literal, Self, final

from punt_lux.domain.hub.bounded_ask import BoundedAsk
from punt_lux.domain.hub.settler import Settler

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from punt_lux.domain.hub.connection_closed import RetireCause
    from punt_lux.domain.hub.dial_generation import DialGeneration
    from punt_lux.protocol import Message

    type Route = Callable[[DialGeneration, Message], None]
    type Capture = Callable[[DialGeneration, RetireCause], bool]

__all__ = ["ListenerHold", "ReaderSlot"]


@final
class ListenerHold:
    """A listener's hold on a dial's reader slot: its settler and its one release.

    Only the slot makes one, and hands it to the listener alone; the release gives the
    hold back when the listener's thread could not be started, honouring any debt an
    end left meanwhile before the slot is free. It can be given back once.
    """

    _settler: Settler
    _give_back: Callable[[Route], None]
    _is_released: bool
    __slots__ = ("_give_back", "_is_released", "_settler")

    def __new__(cls, settler: Settler, give_back: Callable[[Route], None]) -> Self:
        self = super().__new__(cls)
        self._settler = settler
        self._give_back = give_back
        self._is_released = False
        return self

    @property
    def settler(self) -> Settler:
        """The right to settle the dial that the hold carries."""
        return self._settler

    def release(self, held_route: Route) -> None:
        """Give the hold back; the dial is settled over ``held_route`` first if owed."""
        if self._is_released:
            msg = "a listener hold is given back once"
            raise RuntimeError(msg)
        self._is_released = True
        self._give_back(held_route)


@final
class ReaderSlot:
    """Who reads one dial: nobody, its listener thread, or one caller's inline wait."""

    _cond: threading.Condition
    _holder: Literal["none", "listener", "inline"]
    # An end asked for a settle while the slot was held: the holder owes it.
    _debt: bool
    # The thread of an inline holder, so an end it makes itself never waits on it.
    _inline_thread: int | None  # PY-TS-14 OK: absent unless an inline read holds it
    # A dial born held by its listener hands that hold out once.
    _born_unclaimed: bool
    _generation: DialGeneration
    _capture: Capture
    __slots__ = (
        "_born_unclaimed",
        "_capture",
        "_cond",
        "_debt",
        "_generation",
        "_holder",
        "_inline_thread",
    )

    def __new__(
        cls,
        holder: Literal["none", "listener"],
        generation: DialGeneration,
        capture: Capture,
    ) -> Self:
        self = super().__new__(cls)
        self._cond = threading.Condition()
        self._holder = holder
        self._debt = False
        self._inline_thread = None
        self._born_unclaimed = holder == "listener"
        self._generation = generation
        self._capture = capture
        return self

    @property
    def has_listener(self) -> bool:
        """Whether a listener thread holds the slot.

        A bare load, deliberately without the lock: it is one attribute read,
        advisory, and the lock can be held for an inline read's whole wait, which
        no state-lock holder may queue behind.
        """
        return self._holder == "listener"

    def claim_for_listener(self, route: Route) -> ListenerHold | None:
        """Take the slot for a listener; its hold, or ``None`` if one holds it.

        Waits out a caller's inline read in flight: a dial has one reader at a
        time, so two threads never feed one frame buffer.
        """
        with self._cond:
            self._cond.wait_for(lambda: self._holder != "inline")
            if self._holder == "listener":
                return None
            self._holder = "listener"
        return self._hold(route)

    def hold_born(self, route: Route) -> ListenerHold:
        """The hold of the listener the dial was born holding the slot for, once.

        Raises ``RuntimeError`` if the dial was not born held, or the hold was
        already handed out: a hold is the holder's, so there is one.
        """
        with self._cond:
            if not self._born_unclaimed:
                msg = "this dial has no unclaimed born hold on its reader slot"
                raise RuntimeError(msg)
            self._born_unclaimed = False
        return self._hold(route)

    @contextlib.contextmanager
    def inline(self, route: Route) -> Generator[Settler | None]:
        """Hold the slot for a caller's inline read; yield its settler, or ``None``.

        ``None`` means a listener or another caller is reading: wait on the sink,
        which that reader feeds. No debt is left by being refused: this is a reader
        waiting for its reply, not an end asking for a settle. Letting go honours any
        debt an end left while it read.
        """
        settler = self._take(route)
        try:
            yield settler
        finally:
            if settler is not None:
                self._release(settler)

    def ask_settle(self, route: Route, cause: RetireCause, *, may_wait: bool) -> None:
        """Ask for the dial to be settled, an end having been recorded or requested.

        A free slot is taken and the dial settled here. A held slot is refused and a
        debt left, in the one critical section that saw it held; the holder settles
        before it lets go. The asker then waits for the bound, and past it settles
        the dial itself with ``cause``, unless it is the holder's own thread
        (``may_wait`` false, or the inline holder itself): its debt is enough, since
        the holder settles when it returns and a wait on itself could only time out.
        """
        with self._cond:
            granted = self._holder == "none"
            if granted:
                self._holder = "inline"
                self._inline_thread = threading.get_ident()
            else:
                self._debt = True
                may_wait = may_wait and self._inline_thread != threading.get_ident()
        if granted:
            settler = self._settler(route)
            try:
                settler.settle()
            finally:
                self._release(settler)
        elif may_wait:
            BoundedAsk(self._generation, self._capture).settle_by_bound(cause)

    def _take(self, route: Route) -> Settler | None:
        """Take the slot for an inline read if free; its settler, else ``None``."""
        with self._cond:
            if self._holder != "none":
                return None
            self._holder = "inline"
            self._inline_thread = threading.get_ident()
        return self._settler(route)

    def _settler(self, route: Route) -> Settler:
        return Settler(self._generation, route, self._capture)

    def _hold(self, route: Route) -> ListenerHold:
        """The listener's hold: its settler over ``route``, and its one release."""
        return ListenerHold(
            self._settler(route),
            lambda held_route: self._release(self._settler(held_route)),
        )

    def _release(self, settler: Settler) -> None:
        """Let go of the slot, settling first for as long as a debt is owed.

        The debt is read in the one critical section that frees the slot, so an end
        that finds the slot held and leaves a debt is never left behind a release
        that missed it.
        """
        while True:
            with self._cond:
                if not self._debt:
                    self._holder = "none"
                    self._inline_thread = None
                    self._cond.notify_all()
                    return
                self._debt = False
            try:
                settler.settle()
            except BaseException:
                self._free()
                raise

    def _free(self) -> None:
        with self._cond:
            self._holder = "none"
            self._inline_thread = None
            self._cond.notify_all()
