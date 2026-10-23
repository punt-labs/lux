"""MenuEntry -- the one entry an applet registers, whole or not at all."""

from __future__ import annotations

import pytest

from punt_lux.applets.menu_entry import MenuEntry


@pytest.mark.parametrize(
    ("callback_id", "label", "frame_id", "empty"),
    [
        ("", "Beads", "frame", "callback_id"),
        ("beads", "", "frame", "label"),
        ("beads", "Beads", "", "frame_id"),
    ],
)
def test_an_entry_with_an_empty_field_is_refused(
    callback_id: str, label: str, frame_id: str, empty: str
) -> None:
    with pytest.raises(ValueError, match=empty):
        MenuEntry(callback_id, label, frame_id)


def test_an_entry_owns_the_clicks_that_carry_its_id() -> None:
    entry = MenuEntry("beads", "Beads", "frame")

    assert (entry.owns("beads"), entry.owns("other")) == (True, False)
