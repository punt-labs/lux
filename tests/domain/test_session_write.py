"""SessionWrite — one registry write, read as a menu change and as a slot change."""

from __future__ import annotations

from typing import final

from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.client_session import ClientSession
from punt_lux.domain.hub.session_callback import SessionCallback
from punt_lux.domain.hub.session_write import Attachment, SessionWrite


@final
class _Leg:
    """A listen leg stand-in; the session needs one to hold, not one that pushes."""

    def wake(self) -> None:
        """Delivery is elsewhere: this class exists to occupy the slot."""


def _agent() -> ClientIdentity:
    return ClientIdentity(kind="mcp-session", name="claude", repo="/w/lux")


def test_recording_into_nothing_starts_a_session_at_now() -> None:
    write = SessionWrite.recorded(None, 5.0, _agent())

    assert write.before is None
    assert write.after.connected_at == 5.0
    assert write.presence == "gained"


def test_recording_without_an_identity_keeps_the_one_declared() -> None:
    declared = ClientSession(0.0).with_identity(_agent())

    write = SessionWrite.recorded(declared, 10.0, None)

    assert write.after.identity == _agent()
    assert write.presence == "unchanged"


def test_attaching_seats_the_listener_and_reports_the_slot() -> None:
    leg = _Leg()

    write = SessionWrite.recorded(None, 0.0, _agent()).seated(leg)

    assert write.after.held_by(leg)
    assert write.attachment == Attachment("attached", "gained", identified=True)


def test_attaching_over_callbacks_reports_them_cleared() -> None:
    first = _Leg()
    seated = SessionWrite.recorded(None, 0.0, _agent()).seated(first).after
    registered = seated.registering(SessionCallback(id="beads", label="Beads"), 0.0)
    assert registered is not None

    write = SessionWrite.recorded(registered, 1.0, _agent()).seated(_Leg())

    assert write.attachment.slot == "attached_over_callbacks"


def test_an_attach_that_clears_callbacks_revises_the_menu_though_presence_held() -> (
    None
):
    assert (
        Attachment("attached_over_callbacks", "unchanged", identified=False).menu_change
        == "revised"
    )


def test_an_attach_that_gains_presence_reports_the_gain() -> None:
    assert (
        Attachment("attached_over_callbacks", "gained", identified=True).menu_change
        == "gained"
    )


class TestIdentified:
    """A write names the connection when the identity it stores is a new one."""

    def test_the_first_declaration_names_a_new_session(self) -> None:
        assert SessionWrite.recorded(None, 0.0, _agent()).identified

    def test_an_anonymous_arrival_names_nobody(self) -> None:
        assert not SessionWrite.recorded(None, 0.0, None).identified

    def test_declaring_the_same_identity_again_names_nobody(self) -> None:
        declared = ClientSession(0.0).with_identity(_agent())

        assert not SessionWrite.recorded(declared, 1.0, _agent()).identified

    def test_a_changed_declaration_names_the_connection_anew(self) -> None:
        declared = ClientSession(0.0).with_identity(_agent())
        other = ClientIdentity(kind="mcp-session", name="claude", repo="/w/other")

        assert SessionWrite.recorded(declared, 1.0, other).identified

    def test_a_bare_contact_with_an_identity_already_held_names_nobody(self) -> None:
        declared = ClientSession(0.0).with_identity(_agent())

        assert not SessionWrite.recorded(declared, 1.0, None).identified

    def test_an_attach_that_declares_names_the_connection(self) -> None:
        write = SessionWrite.recorded(None, 0.0, _agent()).seated(_Leg())

        assert write.attachment.identified

    def test_an_attach_repeating_the_declaration_names_nobody(self) -> None:
        declared = ClientSession(0.0).with_identity(_agent())

        write = SessionWrite.recorded(declared, 1.0, _agent()).seated(_Leg())

        assert not write.attachment.identified


class TestSeated:
    """Seating a listener is the recorded write taking the slot, nothing more."""

    def test_keeps_the_session_it_replaced_and_the_time(self) -> None:
        declared = ClientSession(0.0).with_identity(_agent())
        recorded = SessionWrite.recorded(declared, 4.0, _agent())

        seated = recorded.seated(_Leg())

        assert seated.before is declared
        assert seated.now == 4.0

    def test_carries_the_observed_peer_to_the_stored_session(self) -> None:
        recorded = SessionWrite.recorded(None, 0.0, _agent(), "127.0.0.1")

        seated = recorded.seated(_Leg())

        assert seated.after.peers == ("127.0.0.1",)

    def test_reports_a_new_peer_as_identified_though_the_identity_held(self) -> None:
        held = ClientSession(0.0).with_identity(_agent()).observed_from("127.0.0.1")

        seated = SessionWrite.recorded(held, 1.0, _agent(), "10.0.0.5").seated(_Leg())

        assert seated.attachment.identified

    def test_leaves_the_recorded_write_untouched(self) -> None:
        recorded = SessionWrite.recorded(None, 0.0, _agent())
        leg = _Leg()

        recorded.seated(leg)

        assert not recorded.after.held_by(leg)
