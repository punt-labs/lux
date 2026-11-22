"""MenuListing — whether the Clients menu lists a session, and how a write changes it.

Listed means registered, earning an entry, and in lease at the instant asked: an
entry leaves when its lease lapses whether or not the sweep has removed the session.
"""

from __future__ import annotations

from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.client_session import ClientSession
from punt_lux.domain.hub.menu_listing import MenuListing
from punt_lux.domain.hub.session_callback import SessionCallback

_FAR_FUTURE = 1_000_000.0  # past any kind's lease


def _agent() -> ClientIdentity:
    return ClientIdentity(kind="mcp-session", name="claude", repo="/w/lux")


def _cli() -> ClientIdentity:
    return ClientIdentity(kind="cli", name="lux", repo="/w/lux")


def _change(before: ClientSession | None, after: ClientSession, now: float) -> str:
    return MenuListing(before, now).change_to(MenuListing(after, now))


def test_an_unregistered_connection_lists_nothing() -> None:
    assert not MenuListing(None, 0.0).holds()


def test_a_live_agent_is_listed() -> None:
    assert MenuListing(ClientSession(0.0).with_identity(_agent()), 0.0).holds()


def test_a_lapsed_agent_is_not_listed() -> None:
    agent = ClientSession(0.0).with_identity(_agent())
    assert not MenuListing(agent, _FAR_FUTURE).holds()


def test_a_cli_earns_no_entry() -> None:
    assert not MenuListing(ClientSession(0.0).with_identity(_cli()), 0.0).holds()


def test_a_first_agent_session_gains_presence() -> None:
    assert _change(None, ClientSession(0.0).with_identity(_agent()), 0.0) == "gained"


def test_a_session_earning_nothing_changes_nothing() -> None:
    assert _change(None, ClientSession(0.0).with_identity(_cli()), 0.0) == "unchanged"


def test_renewing_a_live_agent_changes_nothing() -> None:
    agent = ClientSession(0.0).with_identity(_agent())
    assert _change(agent, agent.renewed(10.0), 10.0) == "unchanged"


def test_renewing_a_lapsed_agent_gains_presence_back() -> None:
    agent = ClientSession(0.0).with_identity(_agent())
    assert _change(agent, agent.renewed(_FAR_FUTURE), _FAR_FUTURE) == "gained"


def test_relabelling_a_listed_agent_revises_its_entry() -> None:
    agent = ClientSession(0.0).with_identity(_agent())
    other = ClientIdentity(kind="mcp-session", name="claude", repo="/w/other")
    assert _change(agent, agent.with_identity(other), 0.0) == "revised"


def test_withdrawing_a_listed_entry_revises_the_menu() -> None:
    agent = ClientSession(0.0).with_identity(_agent())
    assert _change(agent, ClientSession(0.0).with_identity(_cli()), 0.0) == "revised"


class _Leg:
    def wake(self) -> None:
        """A leg stand-in; only its identity matters."""


def _registering(session: ClientSession, callback_id: str, now: float) -> ClientSession:
    updated = session.attached(_Leg()).registering(
        SessionCallback(id=callback_id, label="Beads"), now
    )
    assert updated is not None
    return updated


def test_a_new_entry_on_a_listed_agent_revises_the_menu() -> None:
    agent = ClientSession(0.0).with_identity(_agent())

    assert _change(agent, _registering(agent, "beads", 0.0), 0.0) == "revised"


def test_a_changed_entry_label_on_a_listed_session_revises_the_menu() -> None:
    first = _registering(ClientSession(0.0).with_identity(_agent()), "beads", 0.0)
    relabelled = first.registering(SessionCallback(id="beads", label="Board"), 0.0)

    assert relabelled is not None
    assert _change(first, relabelled, 0.0) == "revised"


def test_the_same_entries_on_a_renewed_session_change_nothing() -> None:
    first = _registering(ClientSession(0.0).with_identity(_agent()), "beads", 0.0)

    assert _change(first, first.renewed(10.0), 10.0) == "unchanged"


def test_entries_withdrawn_from_a_lapsed_session_still_revise_the_menu() -> None:
    # A lapse leaves the entry on the Display; only a lapse-blind mark removes it.
    held = _registering(ClientSession(0.0).with_identity(_agent()), "beads", 0.0)

    assert _change(held, held.attached(_Leg()), _FAR_FUTURE) == "revised"
