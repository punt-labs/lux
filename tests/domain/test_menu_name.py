"""What a client's menu name is, and how a set of them stays readable.

A name prints as one string, but it is a base and an ordinal: the base is what a
person calls the holder, the ordinal only separates holders that read the same
way. The first of a name prints bare, a later one carries its number, and falling
back to the base is asking the value for its plain form rather than reading a
number back out of a label.

Over a set of them one invariant holds through every operation: if anybody is
``lux (2)``, somebody is ``lux``. Taking a name keeps it by handing out the
lowest free one; dropping a name restores it by giving the base a departure
freed to the senior holder still numbered against it.
"""

from __future__ import annotations

from punt_lux.domain.hub.menu_name import MenuName, MenuNames
from punt_lux.domain.ids import ConnectionId


class TestWhatANameReadsAs:
    """The label is the whole of what the menu shows for a client."""

    def test_the_first_of_a_name_prints_bare(self) -> None:
        assert MenuName("lux").label == "lux"

    def test_a_later_one_carries_its_number(self) -> None:
        assert MenuName("lux", 2).label == "lux (2)"

    def test_the_ordinal_one_is_the_bare_base(self) -> None:
        """Plain and numbered are one kind of value, so nothing case-splits on it."""
        assert MenuName("lux", 1).label == MenuName("lux").label


class TestFallingBackToThePlainName:
    """What a client is called once it is the only one of its name."""

    def test_a_numbered_name_drops_its_number(self) -> None:
        assert MenuName("lux", 3).plain.label == "lux"

    def test_a_plain_name_is_already_plain(self) -> None:
        assert MenuName("lux").plain.label == "lux"

    def test_the_base_survives_a_label_that_would_be_ambiguous_to_parse(self) -> None:
        """A repository may itself read like a numbered name; the base is no parse."""
        numbered = MenuName("lux (2)", 2)

        assert numbered.label == "lux (2) (2)"
        assert numbered.plain.label == "lux (2)"


class TestTakingTheLowestFreeName:
    """What a new client of a name is called, given what is already held."""

    def test_a_name_nobody_holds_is_taken_bare(self) -> None:
        assert MenuName.unheld("lux", set()).label == "lux"

    def test_the_second_of_a_name_is_numbered_two(self) -> None:
        assert MenuName.unheld("lux", {"lux"}).label == "lux (2)"

    def test_a_freed_number_is_reused_rather_than_skipped(self) -> None:
        assert MenuName.unheld("lux", {"lux", "lux (3)"}).label == "lux (2)"

    def test_names_of_other_bases_never_push_a_number_up(self) -> None:
        assert MenuName.unheld("lux", {"voxd", "quarry (2)"}).label == "lux"


class TestReadingANameInADiagnostic:
    """The repr shows both parts, which the label alone hides."""

    def test_repr_names_the_base_and_the_ordinal(self) -> None:
        assert repr(MenuName("lux", 2)) == "MenuName('lux', 2)"


def _held(*holders: str) -> MenuNames:
    """Names for each of *holders*, all of one base, taken in the order given."""
    names = MenuNames()
    for holder in holders:
        names.take(ConnectionId(holder), "lux")
    return names


class TestTakingANameForAHolder:
    """What a holder is called from the moment it takes a name."""

    def test_the_first_holder_of_a_base_takes_it_bare(self) -> None:
        assert _held("a").labels() == {ConnectionId("a"): "lux"}

    def test_each_holder_after_it_is_numbered(self) -> None:
        assert list(_held("a", "b", "c").labels().values()) == [
            "lux",
            "lux (2)",
            "lux (3)",
        ]

    def test_taking_twice_leaves_a_holder_with_the_name_it_had(self) -> None:
        """Taking is the one operation that adds, so it can never rename anybody."""
        names = _held("a", "b")

        names.take(ConnectionId("b"), "lux")

        assert names.labels()[ConnectionId("b")] == "lux (2)"

    def test_holders_of_different_bases_never_number_each_other(self) -> None:
        names = MenuNames()
        names.take(ConnectionId("a"), "lux")
        names.take(ConnectionId("b"), "voxd")

        assert names.labels() == {ConnectionId("a"): "lux", ConnectionId("b"): "voxd"}


class TestNobodyIsNumberedAgainstAFreeBase:
    """The invariant: if anybody is ``lux (2)``, somebody is ``lux``."""

    def test_the_survivor_of_two_holds_the_base(self) -> None:
        names = _held("a", "b")

        names.drop([ConnectionId("a")])

        assert names.labels() == {ConnectionId("b"): "lux"}

    def test_a_departure_moves_at_most_one_name(self) -> None:
        """Closing the gap would rename a second entry to say nothing new."""
        names = _held("a", "b", "c")

        names.drop([ConnectionId("a")])

        assert names.labels() == {
            ConnectionId("b"): "lux",
            ConnectionId("c"): "lux (3)",
        }

    def test_dropping_a_number_moves_nobody(self) -> None:
        """Only a freed base moves a name; the numbers below it are simply free."""
        names = _held("a", "b", "c")

        names.drop([ConnectionId("b")])

        assert names.labels() == {
            ConnectionId("a"): "lux",
            ConnectionId("c"): "lux (3)",
        }

    def test_the_freed_number_goes_to_the_next_holder_to_take_one(self) -> None:
        names = _held("a", "b", "c")

        names.drop([ConnectionId("b")])
        names.take(ConnectionId("d"), "lux")

        assert names.labels()[ConnectionId("d")] == "lux (2)"

    def test_the_senior_holder_is_the_one_that_moves(self) -> None:
        """Seniority is the order names were taken, not the order they read in."""
        names = _held("first", "second", "old")

        names.drop([ConnectionId("second")])  # frees "lux (2)"
        names.take(ConnectionId("recent"), "lux")  # which "recent" then takes
        names.drop([ConnectionId("first")])  # frees the base

        assert names.labels()[ConnectionId("old")] == "lux"
        assert names.labels()[ConnectionId("recent")] == "lux (2)"

    def test_every_departure_hands_the_base_on_until_one_holder_is_left(self) -> None:
        names = _held("a", "b", "c")

        names.drop([ConnectionId("a")])
        names.drop([ConnectionId("b")])

        assert names.labels() == {ConnectionId("c"): "lux"}

    def test_holders_of_other_bases_are_left_alone(self) -> None:
        names = _held("a", "b")
        names.take(ConnectionId("vox"), "voxd")

        names.drop([ConnectionId("a")])

        assert names.labels()[ConnectionId("vox")] == "voxd"

    def test_dropping_a_holder_that_held_no_name_changes_nothing(self) -> None:
        names = _held("a", "b")

        names.drop([ConnectionId("never-took-one")])

        assert names.labels() == {
            ConnectionId("a"): "lux",
            ConnectionId("b"): "lux (2)",
        }

    def test_dropping_the_same_holder_twice_is_no_error(self) -> None:
        names = _held("a")

        names.drop([ConnectionId("a")])
        names.drop([ConnectionId("a")])

        assert names.labels() == {}
