"""FrameHeading -- a frame's title and the Hub's name for its owner."""

from __future__ import annotations

from punt_lux.display.replica.frame_heading import FrameHeading


def test_holds_the_title_it_is_given() -> None:
    assert FrameHeading("Vox").title == "Vox"


def test_has_no_scope_label_until_the_hub_names_the_owner() -> None:
    assert FrameHeading("Vox").scope_label is None


def test_holds_the_scope_label_it_is_given() -> None:
    assert FrameHeading("Vox", "lux (2)").scope_label == "lux (2)"


class TestAdopt:
    """A content push: what it carries replaces, what it omits is left alone."""

    def test_takes_a_new_title_and_a_new_label(self) -> None:
        heading = FrameHeading("Vox", "lux")

        heading.adopt("Beads", "lux (2)")

        assert (heading.title, heading.scope_label) == ("Beads", "lux (2)")

    def test_an_omitted_title_leaves_the_last_one(self) -> None:
        heading = FrameHeading("Vox", "lux")

        heading.adopt(None, "lux (2)")

        assert (heading.title, heading.scope_label) == ("Vox", "lux (2)")

    def test_an_empty_title_leaves_the_last_one(self) -> None:
        heading = FrameHeading("Vox")

        heading.adopt("", None)

        assert heading.title == "Vox"

    def test_a_missing_label_never_blanks_the_one_held(self) -> None:
        heading = FrameHeading("Vox", "lux")

        heading.adopt("Vox", None)

        assert heading.scope_label == "lux"

    def test_a_label_arrives_on_a_heading_that_had_none(self) -> None:
        heading = FrameHeading("Vox")

        heading.adopt(None, "lux")

        assert heading.scope_label == "lux"

    def test_adopting_nothing_changes_nothing(self) -> None:
        heading = FrameHeading("Vox", "lux")

        heading.adopt(None, None)

        assert (heading.title, heading.scope_label) == ("Vox", "lux")


class TestRelabel:
    """An empty push: the Hub's fresh answer replaces the label, absence included."""

    def test_replaces_the_label(self) -> None:
        heading = FrameHeading("Vox", "lux")

        heading.relabel("lux (2)")

        assert heading.scope_label == "lux (2)"

    def test_takes_the_hubs_absence_where_adopt_would_not(self) -> None:
        heading = FrameHeading("Vox", "lux")

        heading.relabel(None)

        assert heading.scope_label is None

    def test_never_touches_the_title(self) -> None:
        heading = FrameHeading("Vox", "lux")

        heading.relabel(None)

        assert heading.title == "Vox"
