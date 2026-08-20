"""NamedSessions — the live sessions and the menu name each one holds, read as one.

Built by the registry inside its lock, so what it carries was true at one instant:
the clients that were live, and what each of them is called.
"""

from __future__ import annotations

from typing import final

from punt_lux.domain.hub.applet_name_format import format_name
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.client_roster import ClientRoster
from punt_lux.domain.hub.client_session import ClientSession
from punt_lux.domain.hub.named_sessions import NamedSessions
from punt_lux.domain.hub.session_callback import SessionCallback
from punt_lux.domain.ids import ConnectionId


@final
class _SilentLeg:
    """A listen leg stand-in: a client must hold one to hold a command."""

    def wake(self) -> None:
        """No delivery here — these tests are about what a read carries."""


def _beads() -> SessionCallback:
    return SessionCallback(id="beads", label="Beads")


def _session(repo: str | None = "/Users/someone/lux", *commands: SessionCallback):
    """An identified session holding a leg and the commands it registered."""
    session = (
        ClientSession(0.0)
        .with_identity(ClientIdentity(kind="mcp-session", name="claude", repo=repo))
        .attached(_SilentLeg())
    )
    for command in commands:
        session = session.with_callback(command)
    return session


def _over(*sessions: tuple[str, ClientSession]) -> NamedSessions:
    """Name the given connections, in the order they connected."""
    live = {ConnectionId(name): session for name, session in sessions}
    return NamedSessions.over(live, ClientRoster())


class TestNaming:
    """Which sessions are named, and what they are called."""

    def test_an_identified_session_is_named_for_its_repository(self) -> None:
        named = _over(("a", _session()))

        assert named.name_of(ConnectionId("a"), "client") == "lux"

    def test_an_anonymous_session_takes_no_name(self) -> None:
        named = NamedSessions.over(
            {ConnectionId("bare"): ClientSession(0.0)}, ClientRoster()
        )

        assert named.name_of(ConnectionId("bare"), "client") == "client"

    def test_a_connection_that_is_not_in_the_read_falls_back(self) -> None:
        """A click can outlive the client whose entry it came from."""
        named = _over(("a", _session()))

        assert named.name_of(ConnectionId("gone"), "client") == "client"

    def test_two_clients_of_one_repository_are_numbered(self) -> None:
        named = _over(("first", _session()), ("second", _session()))

        assert named.name_of(ConnectionId("first"), "client") == "lux"
        assert named.name_of(ConnectionId("second"), "client") == "lux (2)"


class TestWhatIsCarried:
    """The sessions half of the read."""

    def test_the_sessions_are_the_ones_the_read_was_built_over(self) -> None:
        session = _session()

        named = _over(("a", session))

        assert dict(named.sessions) == {ConnectionId("a"): session}

    def test_a_later_write_to_the_store_does_not_reach_a_finished_read(self) -> None:
        """The read is a copy, so what it reports stays what was true."""
        store = {ConnectionId("a"): _session()}
        named = NamedSessions.over(store, ClientRoster())

        store[ConnectionId("b")] = _session()

        assert list(named.sessions) == [ConnectionId("a")]


class TestCommandingClients:
    """The clients a menu is composed from: named, and holding a command."""

    def test_a_named_client_with_commands_is_yielded(self) -> None:
        named = _over(("a", _session("/Users/someone/lux", _beads())))

        clients = list(named.commanding())

        assert [client.connection_id for client in clients] == [ConnectionId("a")]
        assert [client.name for client in clients] == ["lux"]
        assert [client.callbacks for client in clients] == [(_beads(),)]

    def test_a_named_client_with_no_command_is_left_out(self) -> None:
        named = _over(("a", _session()))

        assert list(named.commanding()) == []

    def test_an_anonymous_client_with_a_command_is_left_out(self) -> None:
        """Nothing anonymous reaches the bar, however much it registered."""
        anonymous = ClientSession(0.0).attached(_SilentLeg()).with_callback(_beads())

        named = NamedSessions.over({ConnectionId("bare"): anonymous}, ClientRoster())

        assert list(named.commanding()) == []

    def test_clients_come_in_connection_order(self) -> None:
        """The order that decides who is the plain ``lux`` decides this too."""
        named = _over(
            ("early", _session("/Users/someone/lux", _beads())),
            ("late", _session("/Users/someone/lux", _beads())),
        )

        assert [client.name for client in named.commanding()] == ["lux", "lux (2)"]


def _applet_session(
    pid: int, program: str, *commands: SessionCallback
) -> ClientSession:
    identity = ClientIdentity(
        kind="applet",
        name=format_name("lux", pid, program),
        repo="/Users/someone/lux",
    )
    session = ClientSession(0.0).with_identity(identity).attached(_SilentLeg())
    for command in commands:
        session = session.with_callback(command)
    return session


class TestCommandingGroups:
    """The submenus a menu is composed from — one per group of shared name."""

    def test_a_non_applet_is_a_one_member_group(self) -> None:
        named = _over(("a", _session("/Users/someone/lux", _beads())))

        groups = list(named.commanding_groups())

        assert [group.name for group in groups] == ["lux"]
        assert [len(group.members) for group in groups] == [1]

    def test_two_applets_in_one_session_are_one_group(self) -> None:
        """DES-067: same (repo, session_pid) yields a two-member group."""
        pid = 12345
        beads = SessionCallback(id="beads", label="Beads")
        music = SessionCallback(id="music", label="Music")

        named = _over(
            ("b", _applet_session(pid, "lux-beads", beads)),
            ("v", _applet_session(pid, "vox-panel", music)),
        )

        groups = list(named.commanding_groups())

        assert [group.name for group in groups] == ["lux"]
        assert len(groups[0].members) == 2
        member_labels = {
            callback.label
            for member in groups[0].members
            for callback in member.callbacks
        }
        assert member_labels == {"Beads", "Music"}

    def test_two_applets_in_different_sessions_are_two_groups(self) -> None:
        """DES-064's collision-numbering still fires between different sessions."""
        beads = SessionCallback(id="beads", label="Beads")

        named = _over(
            ("a", _applet_session(0xAAAA, "lux-beads", beads)),
            ("b", _applet_session(0xBBBB, "lux-beads", beads)),
        )

        groups = list(named.commanding_groups())

        assert sorted(group.name for group in groups) == ["lux", "lux (2)"]

    def test_the_senior_member_of_a_group_is_first(self) -> None:
        """The first-registered applet is the senior, whom Details points at."""
        pid = 12345
        beads = SessionCallback(id="beads", label="Beads")

        named = _over(
            ("first", _applet_session(pid, "lux-beads", beads)),
            ("second", _applet_session(pid, "vox-panel", beads)),
        )

        groups = list(named.commanding_groups())

        assert groups[0].members[0].connection_id == ConnectionId("first")
