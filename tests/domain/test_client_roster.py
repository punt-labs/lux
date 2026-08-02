"""ClientRoster — the names the menu calls the display's clients.

A client is named for where it works, numbered when two read the same way, and
keeps its number until its connection goes. The stability is the point: a menu
entry that renames itself under the pointer is worse than a gap in the numbering.

Departure is told to the roster, never inferred by it. The registry names the
connections it removed as it removes them, so nothing a reader hands over — a
picture of who was live a moment ago — can take a name away.
"""

from __future__ import annotations

from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.client_roster import ClientRoster
from punt_lux.domain.ids import ConnectionId


def _identity(name: str, repo: str | None = None) -> ClientIdentity:
    return ClientIdentity(kind="mcp-session", name=name, repo=repo)


def _lux() -> ClientIdentity:
    return _identity("claude", "/Users/someone/lux")


class TestNaming:
    """What one client is called, before any collision."""

    def test_a_client_is_named_for_its_repository(self) -> None:
        names = ClientRoster().names_for({ConnectionId("a"): _lux()})

        assert names == {ConnectionId("a"): "lux"}

    def test_a_client_with_no_repository_is_named_for_itself(self) -> None:
        names = ClientRoster().names_for({ConnectionId("a"): _identity("voxd")})

        assert names == {ConnectionId("a"): "voxd"}

    def test_nothing_live_is_named_nothing(self) -> None:
        assert ClientRoster().names_for({}) == {}


class TestCollisions:
    """Two clients that read the same way are told apart by a number."""

    def test_the_second_client_of_a_name_is_numbered(self) -> None:
        names = ClientRoster().names_for(
            {ConnectionId("a"): _lux(), ConnectionId("b"): _lux()}
        )

        assert list(names.values()) == ["lux", "lux (2)"]

    def test_a_third_takes_the_next_number(self) -> None:
        names = ClientRoster().names_for(
            {
                ConnectionId("a"): _lux(),
                ConnectionId("b"): _lux(),
                ConnectionId("c"): _lux(),
            }
        )

        assert list(names.values()) == ["lux", "lux (2)", "lux (3)"]

    def test_the_first_connection_takes_the_unnumbered_name(self) -> None:
        """The registry hands over connections in arrival order, so first is first."""
        roster = ClientRoster()

        names = roster.names_for(
            {ConnectionId("early"): _lux(), ConnectionId("late"): _lux()}
        )

        assert names[ConnectionId("early")] == "lux"

    def test_clients_of_different_names_are_never_numbered(self) -> None:
        names = ClientRoster().names_for(
            {ConnectionId("a"): _lux(), ConnectionId("b"): _identity("voxd")}
        )

        assert sorted(names.values()) == ["lux", "voxd"]


class TestStability:
    """A name lasts exactly as long as the connection that holds it."""

    def test_a_name_survives_repeated_reads(self) -> None:
        roster = ClientRoster()
        live = {ConnectionId("a"): _lux(), ConnectionId("b"): _lux()}

        first = roster.names_for(live)
        second = roster.names_for(live)

        assert first == second

    def test_a_numbered_client_is_not_promoted_when_the_first_leaves(self) -> None:
        roster = ClientRoster()
        roster.names_for({ConnectionId("a"): _lux(), ConnectionId("b"): _lux()})

        roster.release([ConnectionId("a")])
        names = roster.names_for({ConnectionId("b"): _lux()})

        assert names == {ConnectionId("b"): "lux (2)"}

    def test_a_departed_clients_name_is_free_for_the_next_arrival(self) -> None:
        roster = ClientRoster()
        roster.names_for({ConnectionId("a"): _lux(), ConnectionId("b"): _lux()})

        roster.release([ConnectionId("a")])
        names = roster.names_for({ConnectionId("b"): _lux(), ConnectionId("c"): _lux()})

        assert names[ConnectionId("b")] == "lux (2)"
        assert names[ConnectionId("c")] == "lux"

    def test_a_client_that_reconnects_as_a_new_connection_is_named_afresh(self) -> None:
        """The name follows the connection, which is what its lifetime is."""
        roster = ClientRoster()
        roster.names_for({ConnectionId("old"): _lux()})

        roster.release([ConnectionId("old")])
        names = roster.names_for({ConnectionId("new"): _lux()})

        assert names == {ConnectionId("new"): "lux"}

    def test_a_departed_client_is_dropped_from_what_is_held(self) -> None:
        roster = ClientRoster()
        roster.names_for({ConnectionId("a"): _lux(), ConnectionId("b"): _lux()})

        roster.release([ConnectionId("a")])

        assert roster.held() == {ConnectionId("b"): "lux (2)"}


class TestWhoMayTakeANameAway:
    """Only the removal of a session frees its name — never the shape of a read."""

    def test_a_read_that_omits_a_named_client_leaves_its_name_alone(self) -> None:
        """The interleaving that made the menu and Details disagree.

        Two readers each took their own picture of the live sessions and each
        released whatever their picture did not show, so a reader holding the older
        picture dropped a name the newer one had just assigned. There is no such
        path now: a set handed to :meth:`names_for` only ever adds.
        """
        roster = ClientRoster()
        first, second = ConnectionId("first"), ConnectionId("second")
        stale = {first: _lux()}
        roster.names_for({first: _lux(), second: _lux()})

        roster.names_for(stale)

        assert roster.held() == {first: "lux", second: "lux (2)"}

    def test_a_read_that_omits_every_named_client_releases_nothing(self) -> None:
        roster = ClientRoster()
        roster.names_for({ConnectionId("a"): _lux()})

        roster.names_for({})

        assert roster.held() == {ConnectionId("a"): "lux"}

    def test_a_name_released_twice_is_no_error(self) -> None:
        """A session may be discarded after the sweep already took it."""
        roster = ClientRoster()
        roster.names_for({ConnectionId("a"): _lux()})

        roster.release([ConnectionId("a")])
        roster.release([ConnectionId("a")])

        assert roster.held() == {}

    def test_releasing_a_connection_that_was_never_named_is_no_error(self) -> None:
        """An anonymous session is swept having never taken a name."""
        roster = ClientRoster()

        roster.release([ConnectionId("never-identified")])

        assert roster.held() == {}


class TestWhatIsHeld:
    """The read anything naming a client afterwards uses."""

    def test_held_reports_the_last_assignment(self) -> None:
        roster = ClientRoster()
        roster.names_for({ConnectionId("a"): _lux()})

        assert roster.held() == {ConnectionId("a"): "lux"}

    def test_held_is_a_copy_a_caller_cannot_write_through(self) -> None:
        roster = ClientRoster()
        roster.names_for({ConnectionId("a"): _lux()})

        roster.held()[ConnectionId("a")] = "something else"

        assert roster.held() == {ConnectionId("a"): "lux"}

    def test_nothing_named_yet_holds_nothing(self) -> None:
        assert ClientRoster().held() == {}
