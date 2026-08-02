"""ClientRoster — the names the menu calls the display's clients.

A client is named for where it works, numbered when two read the same way, and
keeps its number until its connection goes. The stability is the point: a menu
entry that renames itself under the pointer is worse than a gap in the numbering.
"""

from __future__ import annotations

import threading
import time
from typing import final

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

        names = roster.names_for({ConnectionId("b"): _lux()})

        assert names == {ConnectionId("b"): "lux (2)"}

    def test_a_departed_clients_name_is_free_for_the_next_arrival(self) -> None:
        roster = ClientRoster()
        roster.names_for({ConnectionId("a"): _lux(), ConnectionId("b"): _lux()})

        names = roster.names_for({ConnectionId("b"): _lux(), ConnectionId("c"): _lux()})

        assert names[ConnectionId("b")] == "lux (2)"
        assert names[ConnectionId("c")] == "lux"

    def test_a_client_that_reconnects_as_a_new_connection_is_named_afresh(self) -> None:
        """The name follows the connection, which is what its lifetime is."""
        roster = ClientRoster()
        roster.names_for({ConnectionId("old"): _lux()})

        names = roster.names_for({ConnectionId("new"): _lux()})

        assert names == {ConnectionId("new"): "lux"}

    def test_a_departed_client_is_dropped_from_what_is_held(self) -> None:
        roster = ClientRoster()
        roster.names_for({ConnectionId("a"): _lux(), ConnectionId("b"): _lux()})

        roster.names_for({ConnectionId("b"): _lux()})

        assert roster.held() == {ConnectionId("b"): "lux (2)"}


@final
class _SlowIdentity(ClientIdentity):
    """An identity whose name takes a moment to read.

    The roster computes a new name between releasing the departed and storing
    the assignment, and that gap is where two threads collide. On a real
    identity the gap is a few instructions wide and a test would have to be
    lucky to land in it; widening it here does not change what the roster does,
    it only makes the existing window observable.
    """

    @property
    def menu_label(self) -> str:
        time.sleep(0.001)
        return super().menu_label


def _slow_lux() -> ClientIdentity:
    """An identity in the lux repository whose name takes a moment to read."""
    return _SlowIdentity(kind="mcp-session", name="claude", repo="/Users/someone/lux")


class TestUnderConcurrentReads:
    """Three threads read this roster, and every read both assigns and releases."""

    def test_a_read_is_never_corrupted_by_another_read(self) -> None:
        """Two live snapshots taken moments apart, named at the same time.

        The replicator and an introspection read each take their own snapshot of
        the live sessions, so one can be naming a set the other has already seen
        a client leave. Unguarded, one thread's release lands inside the other's
        assignment loop: the name it just stored is deleted before it reads it
        back, which is a KeyError in the menu compose, or it hands one name to
        two connections. Either way the menu and Details stop agreeing.
        """
        roster = ClientRoster()
        gone, stays = ConnectionId("gone"), ConnectionId("stays")
        both = {gone: _slow_lux(), stays: _slow_lux()}
        one = {stays: _slow_lux()}
        failures: list[BaseException] = []
        returned: list[dict[ConnectionId, str]] = []

        def keep_naming(live: dict[ConnectionId, ClientIdentity]) -> None:
            try:
                returned.extend(roster.names_for(live) for _ in range(40))
            except BaseException as exc:  # noqa: BLE001 — the thread's own boundary
                failures.append(exc)

        threads = [
            threading.Thread(target=keep_naming, args=(live,))
            for live in (both, one, both, one)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert failures == [], f"a read raised: {failures[0]!r}"
        for names in returned:
            assert len(set(names.values())) == len(names), f"a name was shared: {names}"

    def test_every_read_returns_a_whole_consistent_set_of_names(self) -> None:
        """A read is one critical section, so no caller sees a partial roster."""
        roster = ClientRoster()
        live = {ConnectionId(f"c{n}"): _lux() for n in range(12)}
        roster.names_for(live)
        seen: list[dict[ConnectionId, str]] = []
        stop = threading.Event()

        def keep_naming() -> None:
            while not stop.is_set():
                roster.names_for(live)

        namer = threading.Thread(target=keep_naming)
        namer.start()
        try:
            seen.extend(roster.held() for _ in range(200))
        finally:
            stop.set()
            namer.join()

        for held in seen:
            assert len(held) == len(live)
            assert len(set(held.values())) == len(live)


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
