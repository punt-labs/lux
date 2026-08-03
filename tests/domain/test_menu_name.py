"""MenuName — the base a client is called and the ordinal telling it from its twins.

A name prints as one string, but it is a base and an ordinal: the base is what a
person calls the client, the ordinal only separates clients that read the same
way. The first of a name prints bare, a later one carries its number, and falling
back to the base is asking the value for its plain form rather than reading a
number back out of a label.
"""

from __future__ import annotations

from punt_lux.domain.hub.menu_name import MenuName


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
