"""Registration and Detachment -- an outcome that always agrees with its write."""

from __future__ import annotations

import pytest

from punt_lux.client_host import UNOBSERVED
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.client_session import ClientSession
from punt_lux.domain.hub.leg_writes import Detachment, Registration
from punt_lux.domain.hub.session_callback import SessionCallback
from punt_lux.domain.hub.session_write import SessionWrite


class _Leg:
    def wake(self) -> None:
        """A leg stand-in; only its identity matters."""


def _agent() -> ClientIdentity:
    return ClientIdentity(kind="mcp-session", name="claude", repo="/w/lux")


def _write() -> SessionWrite:
    return SessionWrite.recorded(None, 0.0, _agent(), UNOBSERVED)


_BEADS = SessionCallback(id="beads", label="Beads")


def _held(callbacks: bool) -> ClientSession:
    session = ClientSession(0.0).with_identity(_agent()).attached(_Leg())
    if callbacks:
        session = session.with_callback(_BEADS)
    return session


class TestRegistration:
    def test_a_registration_that_took_carries_its_write(self) -> None:
        write = SessionWrite(None, _held(callbacks=True), 0.0)

        registration = Registration.took(write, _BEADS)

        assert (registration.outcome, registration.write) == ("registered", write)

    @pytest.mark.parametrize("why", ["superseded", "declined"])
    def test_a_refused_registration_has_no_write_and_changes_nothing(
        self, why: str
    ) -> None:
        registration = Registration.refused(why)  # type: ignore[arg-type]

        assert (registration.write, registration.presence) == (None, "unchanged")

    def test_a_registered_outcome_without_a_write_is_refused(self) -> None:
        with pytest.raises(ValueError, match="disagree"):
            Registration("registered", None)

    def test_a_refusal_with_a_write_is_refused(self) -> None:
        with pytest.raises(ValueError, match="disagree"):
            Registration("declined", _write())

    def test_a_registered_outcome_whose_write_stored_no_callback_is_refused(
        self,
    ) -> None:
        session = _held(callbacks=False)

        with pytest.raises(ValueError, match="did not store"):
            Registration.took(SessionWrite(session, session, 0.0), _BEADS)

    def test_a_registered_outcome_whose_write_stored_a_callback_is_accepted(
        self,
    ) -> None:
        session = _held(callbacks=True)

        registration = Registration.took(SessionWrite(None, session, 0.0), _BEADS)

        assert registration.outcome == "registered"

    def test_a_no_op_write_cannot_claim_a_callback_the_session_does_not_hold(
        self,
    ) -> None:
        session = _held(callbacks=True)
        other = SessionCallback(id="other", label="Other")

        with pytest.raises(ValueError, match="did not store"):
            Registration.took(SessionWrite(session, session, 0.0), other)


class TestDetachment:
    def test_a_release_of_a_session_with_entries_says_so(self) -> None:
        before = _held(callbacks=True)
        released = SessionWrite(before, ClientSession(0.0), 0.0)

        assert Detachment.released(released).outcome == "released_with_callbacks"

    def test_a_release_of_a_session_without_entries_is_a_bare_release(self) -> None:
        before = _held(callbacks=False)
        released = SessionWrite(before, ClientSession(0.0), 0.0)

        assert Detachment.released(released).outcome == "released"

    @pytest.mark.parametrize("why", ["kept", "released_with_session"])
    def test_a_teardown_that_released_nothing_has_no_write(self, why: str) -> None:
        detachment = Detachment.nothing(why)  # type: ignore[arg-type]

        assert (detachment.write, detachment.presence) == (None, "unchanged")

    def test_a_release_outcome_without_a_write_is_refused(self) -> None:
        with pytest.raises(ValueError, match="disagree"):
            Detachment("released", None)

    def test_a_kept_outcome_with_a_write_is_refused(self) -> None:
        with pytest.raises(ValueError, match="disagree"):
            Detachment("kept", _write())

    def test_a_bare_release_of_a_session_that_held_entries_is_refused(self) -> None:
        released = SessionWrite(_held(callbacks=True), ClientSession(0.0), 0.0)

        with pytest.raises(ValueError, match="disagree"):
            Detachment("released", released)

    def test_a_release_with_entries_of_a_session_that_held_none_is_refused(
        self,
    ) -> None:
        released = SessionWrite(_held(callbacks=False), ClientSession(0.0), 0.0)

        with pytest.raises(ValueError, match="disagree"):
            Detachment("released_with_callbacks", released)

    @pytest.mark.parametrize("outcome", ["released", "released_with_callbacks"])
    def test_a_release_outcome_without_a_write_is_refused_for_every_release(
        self, outcome: str
    ) -> None:
        with pytest.raises(ValueError, match="disagree"):
            Detachment(outcome, None)  # type: ignore[arg-type]
