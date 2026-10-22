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

    write = SessionWrite.attached(None, 0.0, _agent(), leg)

    assert write.after.held_by(leg)
    assert write.attachment == Attachment("attached", "gained")


def test_attaching_over_callbacks_reports_them_cleared() -> None:
    first = _Leg()
    seated = SessionWrite.attached(None, 0.0, _agent(), first).after
    registered = seated.registering(SessionCallback(id="beads", label="Beads"), 0.0)
    assert registered is not None

    write = SessionWrite.attached(registered, 1.0, _agent(), _Leg())

    assert write.attachment.slot == "attached_over_callbacks"


def test_an_attach_that_clears_callbacks_revises_the_menu_though_presence_held() -> (
    None
):
    assert Attachment("attached_over_callbacks", "unchanged").menu_change == "revised"


def test_an_attach_that_gains_presence_reports_the_gain() -> None:
    assert Attachment("attached_over_callbacks", "gained").menu_change == "gained"
