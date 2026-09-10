"""DisplayLinkage.classify — a pure four-way truth table, no stored state.

Purely observational: classify derives the Hub's view of the display link from
two facts (connected, live_scene_count) it is handed. No fake, no I/O — the
whole point is that nothing here needs one.
"""

from __future__ import annotations

import pytest

from punt_lux.domain.hub.display_linkage import DisplayLinkage


@pytest.mark.parametrize(
    ("connected", "live_scene_count", "expected"),
    [
        (False, 0, DisplayLinkage.DISCONNECTED),
        (False, 3, DisplayLinkage.HELD),
        (True, 0, DisplayLinkage.CONNECTED_IDLE),
        (True, 2, DisplayLinkage.CONNECTED_ACTIVE),
    ],
)
def test_classify_truth_table(
    *, connected: bool, live_scene_count: int, expected: DisplayLinkage
) -> None:
    assert (
        DisplayLinkage.classify(connected=connected, live_scene_count=live_scene_count)
        is expected
    )
