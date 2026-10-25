"""DisplayRequests -- what the Hub sends the display, and the answers it waits for.

Writes that need no answer (menus, a manifest, a replicated scene) go straight to
the current dial. A ping, a scene shown with ``show`` and a query each send one
request and wait for the one reply it elicits. The reply carries no request id,
so what keeps replies and requests together is order and exclusion: one request
lock per reply kind, held across the write and the wait, so at most one request
of a kind is in flight on a dial; the registration of the reply owed made
before the write; and the
generation the request was written on, which the wait is bound to, so a redial
between the write and the wait fails the waiter instead of handing it the new
dial's reply.

Lock order: a request lock, then the connection's state lock, then the dial's
socket lock, then the sink's lock; a caller holds at most one request lock. A
budget that runs out while waiting for a request lock sends nothing and retires
nothing, and a liveness ping never queues behind a query.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Any, Literal, Self, cast, final

from punt_lux.domain.hub.display_busy import DisplayBusyError
from punt_lux.domain.hub.display_replies import DisplayReplies
from punt_lux.domain.hub.scene_presentation import ScenePresentation
from punt_lux.protocol import (
    AckMessage,
    CallbackMenuMessage,
    HubManifestMessage,
    MenuMessage,
    PingMessage,
    PongMessage,
    QueryRequest,
    QueryResponse,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from punt_lux.domain.hub.dial_generation import DialGeneration
    from punt_lux.domain.hub.display_connection import DisplayConnection
    from punt_lux.domain.hub.display_listener import DisplayListener
    from punt_lux.domain.hub.reply_sink import Pending
    from punt_lux.domain.hub.scene_presentation import SceneLayout
    from punt_lux.protocol import Element, Message, SceneMessage

__all__ = ["DisplayRequests"]

# A ping's timestamp must exceed the last one's by at least this: the wall clock
# alone can repeat within a tick, and a pong is matched by the ts it echoes.
_TS_STEP = 1e-6


@final
class DisplayRequests:
    """Send a request on the current dial and wait for its own reply."""

    _connection: DisplayConnection
    _replies: DisplayReplies
    _budget: float
    _ping_lock: threading.Lock
    _scene_lock: threading.Lock
    _query_lock: threading.Lock
    _last_ts: float
    __slots__ = (
        "_budget",
        "_connection",
        "_last_ts",
        "_ping_lock",
        "_query_lock",
        "_replies",
        "_scene_lock",
    )

    def __new__(
        cls, connection: DisplayConnection, listener: DisplayListener, budget: float
    ) -> Self:
        self = super().__new__(cls)
        self._connection = connection
        self._replies = DisplayReplies(connection, listener)
        self._budget = budget
        self._ping_lock = threading.Lock()
        self._scene_lock = threading.Lock()
        self._query_lock = threading.Lock()
        self._last_ts = 0.0
        return self

    def show(
        self,
        scene_id: str,
        elements: list[Element],
        *,
        title: str | None = None,
        layout: SceneLayout = "single",
        frame_id: str | None = None,
        frame_title: str | None = None,
        frame_size: tuple[int, int] | None = None,
        frame_flags: dict[str, bool] | None = None,
        frame_layout: Literal["tab", "stack"] | None = None,
    ) -> AckMessage | None:
        """Send a scene to the display and wait for acknowledgement.

        Every scene is framed: an omitted *frame_id* self-frames by *scene_id* (as
        the Hub does), so a bare ``show`` still lands in a named frame. Returns the
        :class:`AckMessage` or ``None`` on timeout. The ack is matched by position
        among the acks owed, so scenes written without a wait (the replicator's) are
        accounted for. A timeout keeps the dial; the ack still owed is dropped when
        it arrives.
        """
        presentation = ScenePresentation(
            frame_id=frame_id if frame_id is not None else scene_id,
            title=title,
            layout=layout,
            frame_title=frame_title,
            frame_size=frame_size,
            frame_flags=frame_flags,
            frame_layout=frame_layout,
        )
        msg = presentation.message(scene_id, elements)

        def send(generation: DialGeneration) -> Pending:
            return generation.send_scene(msg, awaited=True)

        try:
            return self._exchange(
                self._scene_lock, AckMessage, None, send, retires=False
            )
        except DisplayBusyError:
            return None

    def send_scene(self, message: SceneMessage) -> None:
        """Send a built scene without waiting for an ack.

        The ack is still owed, and is matched and dropped when it arrives.
        """
        self._connection.require().send_scene(message, awaited=False)

    def set_menu(self, menus: list[dict[str, Any]]) -> None:
        """Set custom menu bar entries."""
        self._send(MenuMessage(menus=menus))

    def set_callback_menus(self, submenus: list[dict[str, Any]]) -> None:
        """Replace the display's Clients menu (Hub-composed)."""
        self._send(CallbackMenuMessage(submenus=submenus))

    def send_manifest(self, scene_ids: Sequence[str]) -> None:
        """Declare the Hub's complete live-scene set to the display (DES-068).

        Meaningful only for a ``kind="hub"`` connection, sent immediately after
        identifying and before any scene content. The display purges every scene
        it cannot attribute to this connection that the manifest does not name.
        """
        self._send(HubManifestMessage(scene_ids=tuple(scene_ids)))

    def probe_alive(self, timeout: float) -> bool:
        """Whether the display answered a ping within ``timeout``.

        The liveness probe the replicator's isolation loop calls between
        successive singleton sends, so a crash caused by scene N attributes to N
        (not N+1). A ping already in flight is itself probing the display, so
        finding the dial busy is not evidence of a dead one: it counts as alive.
        """
        try:
            return self.ping(timeout) is not None
        except DisplayBusyError:
            return True

    def ping(self, timeout: float | None = None) -> PongMessage | None:
        """Ping the display; its pong, or ``None`` if none came in time.

        Raises :class:`DisplayBusyError` if another ping held the dial for the
        whole budget: nothing was sent, so nothing is known of the display. A ping
        that times out keeps its dial: a late pong is dropped, never matched to
        the next ping, whose ``ts`` differs.
        """
        return self._exchange(
            self._ping_lock, PongMessage, timeout, self._send_ping, retires=False
        )

    def query(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> QueryResponse | None:
        """Send a generic query and wait for the response; ``None`` on a timeout.

        Nothing on the wire says which query a response answers, so a query that
        times out retires its dial: the response, if it ever comes, can no longer
        be taken for the next query's.
        """
        request = QueryRequest(method=method, params=params or {})

        def send(generation: DialGeneration) -> Pending:
            pending = generation.sink.expect_query()
            generation.send(request)
            return pending

        try:
            return self._exchange(
                self._query_lock, QueryResponse, timeout, send, retires=True
            )
        except DisplayBusyError:
            return None

    def _send(self, msg: Message) -> None:
        """Write ``msg`` to the current dial; no reply is owed."""
        self._connection.require().send(msg)

    def _send_ping(self, generation: DialGeneration) -> Pending:
        """Register the ping in flight, then write it; under the ping lock."""
        self._last_ts = ts = max(time.time(), self._last_ts + _TS_STEP)
        pending = generation.sink.expect_pong(ts)
        generation.send(PingMessage(ts=ts))
        return pending

    def _exchange[T: Message](
        self,
        lock: threading.Lock,
        expected: type[T],
        timeout: float | None,
        send: Callable[[DialGeneration], Pending],
        *,
        retires: bool,
    ) -> T | None:
        """Hold ``lock`` across ``send`` and the wait for the reply it elicits."""
        budget = self._budget if timeout is None else timeout
        deadline = time.monotonic() + budget
        if not lock.acquire(timeout=max(budget, 0.0)):
            msg = f"a {expected.__name__} request is already in flight"
            raise DisplayBusyError(msg)  # the lock's wait spent the budget
        try:
            generation = self._connection.require()
            pending = send(generation)
            try:
                reply = self._replies.await_reply(generation, pending, deadline)
            finally:
                generation.sink.abandon(pending)
            if reply is None and retires:
                self._connection.close_if_current(generation)
            return cast("T | None", reply)
        finally:
            lock.release()
            # Interactions an inline read held run here: no request lock, no slot.
            self._replies.run_held()
