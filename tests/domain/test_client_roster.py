"""ClientRoster — the names the menu calls the display's clients.

A client is named for where it works and numbered when two read the same way.
The number lasts as long as there is another client to be told apart from: when a
name is released, the base it freed goes back to the senior client still numbered
against it, so nobody is left wearing ``(2)`` alone.

Stability holds over the clients that are here together. While two of one name
are both on the roster neither label changes and the two never swap, because a
removal is the only thing that moves a name — a menu entry that renames itself
under the pointer is worse than a gap in the numbering, and a gap is what a
fallback leaves.

Departure is told to the roster, never inferred by it. The registry names the
connections it removed as it removes them, so nothing a reader hands over — a
picture of who was live a moment ago — can take a name away or promote anybody.
"""

from __future__ import annotations

from punt_lux.domain.hub.applet_name_format import format_name
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.client_roster import ClientRoster
from punt_lux.domain.ids import ConnectionId


def _identity(name: str, repo: str | None = None) -> ClientIdentity:
    return ClientIdentity(kind="mcp-session", name=name, repo=repo)


def _lux() -> ClientIdentity:
    return _identity("claude", "/Users/someone/lux")


_LUX_REPO = "/Users/someone/lux"


def _applet(pid: int, program: str, *, repo: str = _LUX_REPO) -> ClientIdentity:
    return ClientIdentity(
        kind="applet", name=format_name("lux", pid, program), repo=repo
    )


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


class TestStabilityWhileClientsAreTogether:
    """No label moves while the clients holding them are all still here.

    This is the guarantee as it now stands. It used to run for the whole of a
    connection's life — a numbered client kept its number even once the client it
    was numbered against had gone — and that is what left a lone client wearing a
    stale ``(2)``. The protection itself is unchanged and still tested here: reads
    do not rename, an arrival does not renumber the clients already here, and two
    live clients of one name never swap. Only a removal moves a name, and what it
    moves is in :class:`TestFallingBackToAFreedBase`.
    """

    def test_a_name_survives_repeated_reads(self) -> None:
        roster = ClientRoster()
        live = {ConnectionId("a"): _lux(), ConnectionId("b"): _lux()}

        first = roster.names_for(live)
        second = roster.names_for(live)

        assert first == second

    def test_an_arrival_leaves_the_clients_already_here_alone(self) -> None:
        roster = ClientRoster()
        roster.names_for({ConnectionId("a"): _lux(), ConnectionId("b"): _lux()})

        names = roster.names_for(
            {
                ConnectionId("a"): _lux(),
                ConnectionId("b"): _lux(),
                ConnectionId("c"): _lux(),
            }
        )

        assert names[ConnectionId("a")] == "lux"
        assert names[ConnectionId("b")] == "lux (2)"
        assert names[ConnectionId("c")] == "lux (3)"

    def test_two_live_clients_of_one_name_never_swap(self) -> None:
        """The removal of an unrelated client is still a removal — and moves nothing."""
        roster = ClientRoster()
        roster.names_for(
            {
                ConnectionId("a"): _lux(),
                ConnectionId("b"): _lux(),
                ConnectionId("other"): _identity("voxd"),
            }
        )

        roster.release([ConnectionId("other")])

        assert roster.held()[ConnectionId("a")] == "lux"
        assert roster.held()[ConnectionId("b")] == "lux (2)"

    def test_a_client_that_reconnects_as_a_new_connection_is_named_afresh(self) -> None:
        """The name follows the connection, which is what its lifetime is."""
        roster = ClientRoster()
        roster.names_for({ConnectionId("old"): _lux()})

        roster.release([ConnectionId("old")])
        names = roster.names_for({ConnectionId("new"): _lux()})

        assert names == {ConnectionId("new"): "lux"}


class TestFallingBackToAFreedBase:
    """A number lasts only while there is another client to be told apart from."""

    def test_the_survivor_takes_the_plain_name_when_the_first_leaves(self) -> None:
        """The defect: a lone client used to keep the number it arrived with.

        Every session restart overlapped the outgoing session's lease, so the
        arriving client was numbered against one that was already dying and owned
        no menu entry — and it wore that number for its whole connection.
        """
        roster = ClientRoster()
        roster.names_for({ConnectionId("a"): _lux(), ConnectionId("b"): _lux()})

        roster.release([ConnectionId("a")])

        assert roster.held() == {ConnectionId("b"): "lux"}

    def test_the_freed_name_is_what_the_next_read_reports(self) -> None:
        roster = ClientRoster()
        roster.names_for({ConnectionId("a"): _lux(), ConnectionId("b"): _lux()})

        roster.release([ConnectionId("a")])
        names = roster.names_for({ConnectionId("b"): _lux()})

        assert names == {ConnectionId("b"): "lux"}

    def test_a_newcomer_is_numbered_behind_the_client_that_fell_back(self) -> None:
        roster = ClientRoster()
        roster.names_for({ConnectionId("a"): _lux(), ConnectionId("b"): _lux()})

        roster.release([ConnectionId("a")])
        names = roster.names_for({ConnectionId("b"): _lux(), ConnectionId("c"): _lux()})

        assert names[ConnectionId("b")] == "lux"
        assert names[ConnectionId("c")] == "lux (2)"

    def test_only_the_senior_of_three_moves_and_the_rest_keep_their_numbers(
        self,
    ) -> None:
        """One rename per departure: the gap is cheaper than a second rename.

        ``lux (3)`` could be renumbered to ``lux (2)`` to close the gap, but that
        would rename a second entry under the pointer to say nothing new — the
        number is there to tell two clients apart, not to count them off.
        """
        roster = ClientRoster()
        roster.names_for(
            {
                ConnectionId("a"): _lux(),
                ConnectionId("b"): _lux(),
                ConnectionId("c"): _lux(),
            }
        )

        roster.release([ConnectionId("a")])

        assert roster.held() == {ConnectionId("b"): "lux", ConnectionId("c"): "lux (3)"}

    def test_the_last_client_of_a_name_ends_up_holding_it_plainly(self) -> None:
        """Each departure hands the base on, so the survivor of three is ``lux``."""
        roster = ClientRoster()
        roster.names_for(
            {
                ConnectionId("a"): _lux(),
                ConnectionId("b"): _lux(),
                ConnectionId("c"): _lux(),
            }
        )

        roster.release([ConnectionId("a")])
        roster.release([ConnectionId("b")])

        assert roster.held() == {ConnectionId("c"): "lux"}

    def test_the_senior_holder_moves_even_when_a_junior_is_lower_numbered(self) -> None:
        """Seniority decides, not the number — the number is only what got printed.

        ``old`` took ``lux (3)`` before ``recent`` took the ``lux (2)`` a departure
        had freed. When ``lux`` goes it is ``old`` that has been here longest and
        ``old`` that falls back, which is the same rule that gives the plain name
        to the first of several clients arriving together.
        """
        roster = ClientRoster()
        first, old = ConnectionId("first"), ConnectionId("old")
        roster.names_for({first: _lux(), ConnectionId("second"): _lux(), old: _lux()})

        roster.release([ConnectionId("second")])  # frees "lux (2)", not the base
        roster.names_for({first: _lux(), ConnectionId("recent"): _lux()})
        roster.release([first])  # frees the base itself

        assert roster.held()[ConnectionId("old")] == "lux"
        assert roster.held()[ConnectionId("recent")] == "lux (2)"

    def test_a_freed_number_promotes_nobody(self) -> None:
        """Only a freed *base* moves a name; the numbers below it are just free."""
        roster = ClientRoster()
        roster.names_for(
            {
                ConnectionId("a"): _lux(),
                ConnectionId("b"): _lux(),
                ConnectionId("c"): _lux(),
            }
        )

        roster.release([ConnectionId("b")])

        assert roster.held() == {ConnectionId("a"): "lux", ConnectionId("c"): "lux (3)"}

    def test_a_departure_leaves_clients_of_other_names_alone(self) -> None:
        roster = ClientRoster()
        roster.names_for(
            {
                ConnectionId("a"): _lux(),
                ConnectionId("b"): _lux(),
                ConnectionId("vox"): _identity("voxd"),
            }
        )

        roster.release([ConnectionId("a")])

        assert roster.held()[ConnectionId("vox")] == "voxd"

    def test_a_client_the_roster_never_named_frees_nothing(self) -> None:
        """A session swept before it identified took no name, so nothing moves."""
        roster = ClientRoster()
        roster.names_for({ConnectionId("a"): _lux(), ConnectionId("b"): _lux()})

        roster.release([ConnectionId("anonymous")])

        assert roster.held() == {ConnectionId("a"): "lux", ConnectionId("b"): "lux (2)"}


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


class TestAppletGrouping:
    """DES-067: two applets in one session share one name, one submenu.

    The DES-064 numbering keeps firing between different submenus that read
    the same way; it stops firing between two applets of one session, which
    the user reads as one entity.
    """

    def test_two_applets_in_one_session_share_a_name(self) -> None:
        roster = ClientRoster()
        pid = 12345

        names = roster.names_for(
            {
                ConnectionId("beads"): _applet(pid, "lux-beads"),
                ConnectionId("vox"): _applet(pid, "vox-panel"),
            }
        )

        assert names[ConnectionId("beads")] == "lux"
        assert names[ConnectionId("vox")] == "lux"

    def test_two_applets_in_different_sessions_are_still_numbered(self) -> None:
        """DES-064's rule stays for its designed case."""
        roster = ClientRoster()

        names = roster.names_for(
            {
                ConnectionId("a"): _applet(111, "lux-beads"),
                ConnectionId("b"): _applet(222, "lux-beads"),
            }
        )

        assert sorted(names.values()) == ["lux", "lux (2)"]

    def test_a_group_and_a_lone_session_are_numbered_together(self) -> None:
        """Session-A's two applets + session-B's applet = lux and lux (2)."""
        roster = ClientRoster()

        names = roster.names_for(
            {
                ConnectionId("a-beads"): _applet(0xAAAA, "lux-beads"),
                ConnectionId("a-vox"): _applet(0xAAAA, "vox-panel"),
                ConnectionId("b-beads"): _applet(0xBBBB, "lux-beads"),
            }
        )

        assert names[ConnectionId("a-beads")] == "lux"
        assert names[ConnectionId("a-vox")] == "lux"
        assert names[ConnectionId("b-beads")] == "lux (2)"

    def test_releasing_one_sibling_leaves_the_group_named(self) -> None:
        """A group's name lives as long as any of its connections is here."""
        roster = ClientRoster()
        pid = 12345
        roster.names_for(
            {
                ConnectionId("beads"): _applet(pid, "lux-beads"),
                ConnectionId("vox"): _applet(pid, "vox-panel"),
            }
        )

        roster.release([ConnectionId("beads")])

        assert roster.held() == {ConnectionId("vox"): "lux"}

    def test_releasing_the_last_sibling_frees_the_group_base(self) -> None:
        """A different session numbered against the group falls back once empty."""
        roster = ClientRoster()
        roster.names_for(
            {
                ConnectionId("a-beads"): _applet(0xAAAA, "lux-beads"),
                ConnectionId("a-vox"): _applet(0xAAAA, "vox-panel"),
                ConnectionId("b-beads"): _applet(0xBBBB, "lux-beads"),
            }
        )

        roster.release([ConnectionId("a-beads"), ConnectionId("a-vox")])

        assert roster.held() == {ConnectionId("b-beads"): "lux"}

    def test_a_non_applet_never_joins_an_applet_group(self) -> None:
        """A kind that is not ``applet`` is its own submenu, whatever it reads as."""
        roster = ClientRoster()

        names = roster.names_for(
            {
                ConnectionId("applet"): _applet(12345, "lux-beads"),
                ConnectionId("mcp"): _lux(),
            }
        )

        assert sorted(names.values()) == ["lux", "lux (2)"]
