"""FrameHeading -- a frame's title and the Hub's name for its owner."""

from __future__ import annotations

from punt_lux.display.replica.frame_heading import FrameHeading


def test_holds_the_title_it_is_given() -> None:
    assert FrameHeading("Vox").title == "Vox"


def test_has_no_scope_label_until_the_hub_names_the_owner() -> None:
    assert FrameHeading("Vox").scope_label is None


def test_holds_the_scope_label_it_is_given() -> None:
    assert FrameHeading("Vox", "lux (2)").scope_label == "lux (2)"


def test_the_title_and_the_label_move_independently() -> None:
    heading = FrameHeading("Vox", "lux")

    heading.title = "Beads"
    assert (heading.title, heading.scope_label) == ("Beads", "lux")

    heading.scope_label = "lux (2)"
    assert (heading.title, heading.scope_label) == ("Beads", "lux (2)")


def test_the_label_can_be_withdrawn() -> None:
    heading = FrameHeading("Vox", "lux")

    heading.scope_label = None

    assert heading.scope_label is None
    assert heading.title == "Vox"
