"""ClientSession — the session record: connect time, identity, lease, callbacks.

A session starts unidentified with a grace lease, gains an identity (and that
kind's lease length) on declaration without resetting its connect time, and is
renewed by any contact. Its menu callbacks live on the session: it accepts one
only while it holds a listen leg, is identified, and is in lease; it carries them
across renewals and re-identify, and hands them over intact for the registry to
sweep with the session.

The sessions here attach a leg before registering, which is the order a real
connect follows — a callback is delivered by push, so one with no leg to push to
is a state the slot refuses to hold.
"""

from __future__ import annotations

import time
from typing import final

import pytest

from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.client_session import ClientSession
from punt_lux.domain.hub.lease_term import ExpiringLease, PermanentLease
from punt_lux.domain.hub.session_callback import SessionCallback
from punt_lux.domain.hub.session_lease import SessionLease


@final
class _Leg:
    """A listen leg stand-in; the session needs one to hold, not one that pushes."""

    def wake(self) -> None:
        """Delivery is elsewhere: this class exists to occupy the slot."""


def _cli() -> ClientIdentity:
    return ClientIdentity(kind="cli", name="lux", repo="/w/lux")


def _beads() -> SessionCallback:
    return SessionCallback(id="beads", label="Beads")


def _listening() -> ClientSession:
    """A session holding a leg, ready to be handed a callback."""
    return ClientSession(0.0).attached(_Leg())


def test_session_starts_unidentified_with_a_grace_lease() -> None:
    session = ClientSession(0.0)
    assert session.identity is None
    assert session.is_live(0.0)
    assert not session.is_live(1801.0)  # the unidentified grace has lapsed


def test_with_identity_keeps_the_connect_time_and_sets_the_kind_lease() -> None:
    declared = ClientSession(0.0).with_identity(_cli())
    assert declared.identity == _cli()
    assert declared.connected_at == 0.0
    # A cli session's lease is short: live now, lapsed well before the grace would.
    assert declared.is_live(89.0)
    assert not declared.is_live(91.0)


def test_renewed_keeps_identity_and_connect_time_but_extends_the_lease() -> None:
    session = ClientSession(0.0).with_identity(_cli())
    assert not session.is_live(100.0)  # the original cli lease lapsed by 100s

    renewed = session.renewed(80.0)
    assert renewed.identity == _cli()
    assert renewed.connected_at == 0.0
    assert renewed.is_live(100.0)  # renewed at 80s, still inside the 90s window


def test_the_lease_term_reported_is_the_effective_one_not_the_declared() -> None:
    """A session that named no TTL holds its kind's, and reports that."""
    assert ClientSession(0.0).with_identity(_cli()).lease_term == ExpiringLease(
        seconds=90.0
    )
    app = ClientIdentity(kind="app", name="voxd")
    assert ClientSession(0.0).with_identity(app).lease_term == PermanentLease()


def test_declared_repo_is_the_identity_repo_or_none() -> None:
    assert ClientSession(0.0).declared_repo is None  # unidentified
    assert ClientSession(0.0).with_identity(_cli()).declared_repo == "/w/lux"


def test_age_never_goes_negative_under_a_backward_clock_step() -> None:
    session = ClientSession(100.0)
    # A monotonic reading behind the stamp (a stepped clock) still reads zero.
    assert session.age(99.0) == 0.0
    assert session.age(103.5) == pytest.approx(3.5)


def test_a_supplied_lease_is_held_verbatim() -> None:
    lease = SessionLease(renewed_at=5.0, ttl_seconds=10.0)
    session = ClientSession(0.0, lease=lease)
    assert session.is_live(15.0)
    assert not session.is_live(15.1)


def test_uses_a_real_monotonic_stamp_by_default() -> None:
    # Sanity: a freshly-stamped session is live at the current monotonic reading.
    session = ClientSession(time.monotonic())
    assert session.is_live(time.monotonic())


def test_a_new_session_owns_no_callbacks() -> None:
    session = ClientSession(0.0)
    assert session.callbacks == ()
    assert not session.owns_callback("beads")


def test_with_callback_registers_it_and_reports_ownership() -> None:
    session = _listening().with_callback(_beads())
    assert session.owns_callback("beads")
    assert session.callbacks == (_beads(),)


def test_with_callback_replaces_the_earlier_callback_of_the_same_id() -> None:
    session = (
        _listening()
        .with_callback(SessionCallback(id="beads", label="Beads"))
        .with_callback(SessionCallback(id="beads", label="Beads Browser"))
    )
    assert session.callbacks == (SessionCallback(id="beads", label="Beads Browser"),)


def test_a_session_with_no_leg_cannot_be_handed_a_callback() -> None:
    """The slot's refusal reaches the session, because the slot is where it lives.

    The registry never asks for this — it compares the leg it gated against before
    it commits — so the raise marks a caller that skipped the gate rather than a
    condition the running system meets.
    """
    with pytest.raises(ValueError, match="callback needs its listener"):
        ClientSession(0.0).with_callback(_beads())


def test_renewed_and_with_identity_carry_the_callbacks_forward() -> None:
    session = _listening().with_callback(_beads())
    assert session.renewed(10.0).owns_callback("beads")
    assert session.with_identity(_cli()).owns_callback("beads")


def test_an_identified_live_session_accepts_a_callback() -> None:
    session = _listening().with_identity(_cli())
    accepted = session.registering(_beads(), now=10.0)
    assert accepted is not None
    assert accepted.owns_callback("beads")


def test_an_unidentified_session_declines_a_callback() -> None:
    assert _listening().registering(_beads(), now=10.0) is None


def test_a_lapsed_session_declines_a_callback() -> None:
    session = _listening().with_identity(_cli())
    # Past the 90s cli lease — the session declines rather than accrue a dead entry.
    assert session.registering(_beads(), now=100.0) is None
