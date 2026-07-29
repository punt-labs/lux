"""CallbackRouter — routing a click's invocation to the owning session's hold.

A click for a live session that registered the callback is held for that session;
a click for a lapsed session is ``provider_gone`` and one for a callback the live
session never registered is ``unknown_callback``. Holds are per-session (two
sessions never share one), bounded (the oldest is dropped past capacity), taken
by the delivery legs, and swept when a session leaves the live set.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import final

from punt_lux.domain.hub.callback_hold import CallbackRouter
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.client_session import ClientSession
from punt_lux.domain.hub.session_callback import CallbackInvocation, SessionCallback
from punt_lux.domain.ids import ConnectionId


@final
class _Live:
    """A fixed live-session set standing in for the client registry read."""

    def __init__(self, sessions: dict[ConnectionId, ClientSession]) -> None:
        self._sessions = sessions

    def live_sessions(self) -> dict[ConnectionId, ClientSession]:
        return dict(self._sessions)


@final
class _Waker:
    """A CallbackListener counting wakes; an optional side effect proves lock state."""

    def __init__(self, on_wake: Callable[[], None] | None = None) -> None:
        self.wakes = 0
        self._on_wake = on_wake

    def wake(self) -> None:
        self.wakes += 1
        if self._on_wake is not None:
            self._on_wake()


def _session(name: str, *callback_ids: str) -> ClientSession:
    session = ClientSession(0.0).with_identity(
        ClientIdentity(kind="mcp-session", name=name, repo=f"/w/{name}")
    )
    for callback_id in callback_ids:
        session = session.with_callback(SessionCallback(id=callback_id, label="Beads"))
    return session


def test_a_click_for_a_registered_callback_is_held_for_its_session() -> None:
    conn = ConnectionId("vox")
    router = CallbackRouter(_Live({conn: _session("vox", "beads")}))
    outcome = router.route(CallbackInvocation(conn, "beads"))
    assert outcome == "routed"
    assert router.pending(conn) == (CallbackInvocation(conn, "beads"),)


def test_a_click_for_a_lapsed_or_absent_session_reports_provider_gone() -> None:
    conn = ConnectionId("gone")
    router = CallbackRouter(_Live({}))  # the session has left the live set
    assert router.route(CallbackInvocation(conn, "beads")) == "provider_gone"
    assert router.pending(conn) == ()


def test_a_click_for_an_unregistered_callback_is_unknown() -> None:
    conn = ConnectionId("vox")
    router = CallbackRouter(_Live({conn: _session("vox", "beads")}))
    assert router.route(CallbackInvocation(conn, "other")) == "unknown_callback"
    assert router.pending(conn) == ()


def test_two_sessions_never_share_a_hold() -> None:
    vox, lux = ConnectionId("vox"), ConnectionId("lux")
    router = CallbackRouter(
        _Live({vox: _session("vox", "beads"), lux: _session("lux", "beads")})
    )
    router.route(CallbackInvocation(vox, "beads"))
    router.route(CallbackInvocation(lux, "beads"))
    assert router.pending(vox) == (CallbackInvocation(vox, "beads"),)
    assert router.pending(lux) == (CallbackInvocation(lux, "beads"),)


def test_the_hold_is_bounded_dropping_the_oldest() -> None:
    conn = ConnectionId("vox")
    router = CallbackRouter(_Live({conn: _session("vox", "beads")}), capacity=2)
    for _ in range(5):
        router.route(CallbackInvocation(conn, "beads"))
    pending = router.pending(conn)
    assert len(pending) == 2  # capped at capacity, oldest dropped


def test_take_clears_the_hold_and_pending_does_not() -> None:
    conn = ConnectionId("vox")
    router = CallbackRouter(_Live({conn: _session("vox", "beads")}))
    router.route(CallbackInvocation(conn, "beads"))
    assert router.pending(conn) == (CallbackInvocation(conn, "beads"),)  # still held
    assert router.take(conn) == (CallbackInvocation(conn, "beads"),)
    assert router.pending(conn) == ()  # drained


def test_a_departed_session_has_its_hold_swept() -> None:
    conn = ConnectionId("vox")
    live = _Live({conn: _session("vox", "beads")})
    router = CallbackRouter(live)
    router.route(CallbackInvocation(conn, "beads"))
    assert router.pending(conn) == (CallbackInvocation(conn, "beads"),)

    live._sessions.clear()  # the session's lease lapses; it leaves the live set
    # The next routing sweeps the departed session's hold rather than stranding it.
    router.route(CallbackInvocation(ConnectionId("other"), "x"))
    assert router.pending(conn) == ()


def test_pending_sweeps_an_expired_session_without_a_route_in_between() -> None:
    conn = ConnectionId("vox")
    live = _Live({conn: _session("vox", "beads")})
    router = CallbackRouter(live)
    router.route(CallbackInvocation(conn, "beads"))

    live._sessions.clear()  # the lease lapses; no route() fires after this
    # pending() itself sweeps against the live set, so the hold dies with the lease.
    assert router.pending(conn) == ()


def test_take_sweeps_an_expired_session_without_a_route_in_between() -> None:
    conn = ConnectionId("vox")
    live = _Live({conn: _session("vox", "beads")})
    router = CallbackRouter(live)
    router.route(CallbackInvocation(conn, "beads"))

    live._sessions.clear()  # the lease lapses; no route() fires after this
    assert router.take(conn) == ()


def test_a_routed_invocation_wakes_the_connections_listener() -> None:
    conn = ConnectionId("vox")
    router = CallbackRouter(_Live({conn: _session("vox", "beads")}))
    waker = _Waker()
    router.add_listener(conn, waker)
    assert router.route(CallbackInvocation(conn, "beads")) == "routed"
    assert waker.wakes == 1


def test_a_rejected_click_never_wakes_a_listener() -> None:
    conn = ConnectionId("vox")
    router = CallbackRouter(_Live({conn: _session("vox", "beads")}))
    waker = _Waker()
    router.add_listener(conn, waker)
    # unknown_callback and provider_gone both short-circuit before the hold/notify.
    assert router.route(CallbackInvocation(conn, "other")) == "unknown_callback"
    assert (
        router.route(CallbackInvocation(ConnectionId("gone"), "x")) == "provider_gone"
    )
    assert waker.wakes == 0


def test_a_removed_listener_is_no_longer_woken() -> None:
    conn = ConnectionId("vox")
    router = CallbackRouter(_Live({conn: _session("vox", "beads")}))
    waker = _Waker()
    router.add_listener(conn, waker)
    router.remove_listener(conn)
    router.route(CallbackInvocation(conn, "beads"))
    assert waker.wakes == 0


def test_the_wake_runs_outside_the_router_lock() -> None:
    # A reentrant router call inside wake() would deadlock on the non-reentrant lock
    # if the notify ran under it; that it returns proves the wake is post-release.
    conn = ConnectionId("vox")
    router = CallbackRouter(_Live({conn: _session("vox", "beads")}))
    observed: list[tuple[CallbackInvocation, ...]] = []
    router.add_listener(
        conn, _Waker(on_wake=lambda: observed.append(router.pending(conn)))
    )
    router.route(CallbackInvocation(conn, "beads"))
    # The reentrant pending() saw the just-held invocation and did not deadlock.
    assert observed == [(CallbackInvocation(conn, "beads"),)]


def test_the_persistent_listener_and_the_poll_hold_are_the_same_buffer() -> None:
    # A woken listener drains via take(), the identical hold a poller would drain.
    conn = ConnectionId("vox")
    router = CallbackRouter(_Live({conn: _session("vox", "beads")}))
    router.add_listener(conn, _Waker())
    router.route(CallbackInvocation(conn, "beads"))
    assert router.take(conn) == (CallbackInvocation(conn, "beads"),)
    assert router.pending(conn) == ()
