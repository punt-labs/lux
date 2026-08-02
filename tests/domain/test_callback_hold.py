"""CallbackRouter — routing a click's invocation to the owning session's hold.

A click for a live session that registered the callback is held for that session;
a click for a lapsed session is ``provider_gone`` and one for a callback the live
session never registered is ``unknown_callback``. Holds are per-session (two
sessions never share one), bounded (the oldest is dropped past capacity), taken
by the delivery legs, and swept when a session leaves the live set.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, final

from punt_lux.domain.hub.callback_hold import _HOLD_CAPACITY, CallbackRouter
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.client_session import ClientSession
from punt_lux.domain.hub.session_callback import CallbackInvocation, SessionCallback
from punt_lux.domain.ids import ConnectionId

if TYPE_CHECKING:
    import pytest

    from punt_lux.domain.hub.callback_ports import CallbackListener


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


def _session(
    name: str, *callback_ids: str, leg: CallbackListener | None = None
) -> ClientSession:
    """Build a live session holding ``leg``, or an anonymous one, as its connection.

    Every session here holds a leg: a callback is delivered by push, so the slot
    will not hold one for a session with nothing to push to. The leg is attached
    before the callbacks because taking the slot clears what its previous occupant
    owned — the order a real connect follows. A test that cares which listener is
    woken names its own; the rest take one they never look at.
    """
    session = ClientSession(0.0).with_identity(
        ClientIdentity(kind="mcp-session", name=name, repo=f"/w/{name}")
    )
    session = session.attached(leg if leg is not None else _Waker())
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


def test_a_full_hold_says_which_click_it_drops(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The bound is a backstop, and reaching it costs a click somebody was promised.

    Every discarded invocation was answered ``routed``, exactly like the ones a
    departing hold reports. Relying on the deque's silent overflow made this the
    one loss in the module with no line anywhere recording it, so the drop names
    the connection and the callback it discarded.
    """
    conn = ConnectionId("vox")
    router = CallbackRouter(_Live({conn: _session("vox", "beads", "extra")}))
    assert router.route(CallbackInvocation(conn, "beads")) == "routed"

    with caplog.at_level(logging.WARNING):
        for _ in range(_HOLD_CAPACITY):  # the last one overruns the bound
            assert router.route(CallbackInvocation(conn, "extra")) == "routed"

    assert caplog.text.count("hold is full") == 1  # only the overrun warns
    assert "vox" in caplog.text
    assert "beads" in caplog.text  # the oldest, named
    assert len(router.pending(conn)) == _HOLD_CAPACITY


def test_a_hold_below_its_bound_drops_nothing_and_says_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    conn = ConnectionId("vox")
    router = CallbackRouter(_Live({conn: _session("vox", "beads")}), capacity=2)
    with caplog.at_level(logging.WARNING):
        router.route(CallbackInvocation(conn, "beads"))
        router.route(CallbackInvocation(conn, "beads"))
    assert caplog.text == ""
    assert len(router.pending(conn)) == 2


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


def test_a_sweep_that_loses_clicks_says_so(caplog: pytest.LogCaptureFixture) -> None:
    """Every swept invocation was answered ``routed`` — a promise that went unkept.

    The caller was told the click had been handed off to its session. If the hold
    goes with the session before any leg drains it, that work never ran and no
    other line in the system records it, so the sweep names the count and the
    connection rather than dropping them in silence.
    """
    conn = ConnectionId("vox")
    live = _Live({conn: _session("vox", "beads")})
    router = CallbackRouter(live)
    router.route(CallbackInvocation(conn, "beads"))
    router.route(CallbackInvocation(conn, "beads"))

    live._sessions.clear()
    with caplog.at_level(logging.WARNING):
        assert router.pending(conn) == ()

    assert "vox" in caplog.text
    assert "2 routed invocation(s) never delivered" in caplog.text


def test_a_session_that_leaves_with_nothing_owed_is_silent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The warning marks lost work, not departure — the ordinary exit stays quiet."""
    conn = ConnectionId("vox")
    live = _Live({conn: _session("vox", "beads")})
    router = CallbackRouter(live)
    router.route(CallbackInvocation(conn, "beads"))
    assert len(router.take(conn)) == 1  # the leg drained it before the lease lapsed

    live._sessions.clear()
    with caplog.at_level(logging.WARNING):
        router.route(CallbackInvocation(ConnectionId("other"), "x"))

    assert caplog.text == ""


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
    waker = _Waker()
    router = CallbackRouter(_Live({conn: _session("vox", "beads", leg=waker)}))
    assert router.route(CallbackInvocation(conn, "beads")) == "routed"
    assert waker.wakes == 1


def test_a_rejected_click_never_wakes_a_listener() -> None:
    conn = ConnectionId("vox")
    waker = _Waker()
    router = CallbackRouter(_Live({conn: _session("vox", "beads", leg=waker)}))
    # unknown_callback and provider_gone both short-circuit before the hold/notify.
    assert router.route(CallbackInvocation(conn, "other")) == "unknown_callback"
    assert (
        router.route(CallbackInvocation(ConnectionId("gone"), "x")) == "provider_gone"
    )
    assert waker.wakes == 0


def test_a_session_that_released_its_leg_is_no_longer_woken() -> None:
    """The slot is the session's, so a released one leaves nothing to wake.

    Its entries go with it: they were deliverable only to the leg that registered
    them, so the click that used to route now finds no such callback at all.
    """
    conn = ConnectionId("vox")
    waker = _Waker()
    session = _session("vox", "beads", leg=waker)
    live = _Live({conn: session})
    router = CallbackRouter(live)

    torn_down = session.detached(waker)  # the leg tore down and released the slot
    assert torn_down is not None
    live._sessions[conn] = torn_down

    assert router.route(CallbackInvocation(conn, "beads")) == "unknown_callback"
    assert waker.wakes == 0


def test_the_wake_runs_outside_the_router_lock() -> None:
    # A reentrant router call inside wake() would deadlock on the non-reentrant lock
    # if the notify ran under it; that it returns proves the wake is post-release.
    conn = ConnectionId("vox")
    observed: list[tuple[CallbackInvocation, ...]] = []
    waker = _Waker(on_wake=lambda: observed.append(router.pending(conn)))
    router = CallbackRouter(_Live({conn: _session("vox", "beads", leg=waker)}))
    router.route(CallbackInvocation(conn, "beads"))
    # The reentrant pending() saw the just-held invocation and did not deadlock.
    assert observed == [(CallbackInvocation(conn, "beads"),)]


def test_the_live_read_precedes_the_router_lock() -> None:
    # PR-1's invariant: the live read (the client-registry side) completes before
    # the router lock is taken, so the two never nest. A LiveSessions that reenters
    # a lock-taking router method during that read would deadlock on the
    # non-reentrant router lock if the order were reversed; that route() returns
    # proves the read stays outside the lock.
    conn = ConnectionId("vox")
    session = _session("vox", "beads")
    probe: list[tuple[CallbackInvocation, ...]] = []

    @final
    class _Reentrant:
        def __init__(self) -> None:
            self.router: CallbackRouter | None = None
            self._entered = False

        def live_sessions(self) -> dict[ConnectionId, ClientSession]:
            if self.router is not None and not self._entered:
                self._entered = True  # one-shot, or pending() would recurse forever
                probe.append(self.router.pending(ConnectionId("probe")))
            return {conn: session}

    live = _Reentrant()
    router = CallbackRouter(live)
    live.router = router
    assert router.route(CallbackInvocation(conn, "beads")) == "routed"  # no deadlock
    assert probe == [()]  # the reentrant router read completed and saw nothing


def test_the_persistent_listener_and_the_poll_hold_are_the_same_buffer() -> None:
    # A woken listener drains via take(), the identical hold a poller would drain.
    conn = ConnectionId("vox")
    router = CallbackRouter(_Live({conn: _session("vox", "beads", leg=_Waker())}))
    router.route(CallbackInvocation(conn, "beads"))
    assert router.take(conn) == (CallbackInvocation(conn, "beads"),)
    assert router.pending(conn) == ()


def _raise() -> None:
    msg = "listener loop already closing"
    raise RuntimeError(msg)


def test_a_raising_listener_is_isolated_and_the_click_is_kept() -> None:
    """A wake that raises must not fail the route, and must not release the slot.

    A listener whose loop or socket is tearing down may raise. The hold write has
    already happened, so the click survives. The leg stays where it is: the slot
    belongs to the session that installed it and only that session's teardown may
    release it, so a router that cleared it here would be a second writer to state
    it does not own — the clobber the whole design rules out.
    """
    conn = ConnectionId("vox")
    boom = _Waker(on_wake=_raise)
    live = _Live({conn: _session("vox", "beads", leg=boom)})
    router = CallbackRouter(live)

    # Routing survives the raising wake and reports success — the click landed.
    assert router.route(CallbackInvocation(conn, "beads")) == "routed"
    assert router.pending(conn) == (CallbackInvocation(conn, "beads"),)  # kept
    assert boom.wakes == 1

    # The leg is still the session's, so the next click is offered to it again and
    # is buffered just the same; the session's own teardown is what ends this.
    assert router.route(CallbackInvocation(conn, "beads")) == "routed"
    assert boom.wakes == 2
    assert live._sessions[conn].held_by(boom)
    assert len(router.pending(conn)) == 2  # both clicks held for the drain
