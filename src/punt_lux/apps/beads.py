"""Beads Browser — load beads issues for display, in board order."""

from __future__ import annotations

from typing import TYPE_CHECKING

from punt_lux.apps._beads_payload import BeadsLoader

if TYPE_CHECKING:
    from punt_lux.apps.beads_load import BeadsLoad


class BeadsBrowser:
    """Fetch beads issues in the order the board shows them.

    The browser is the data provider a session runs from its own repo shell.
    Request construction lives on ``BeadsBoard``, payload shaping on
    ``BeadsPayloadBuilder``, and the session pushes the result to the Hub through
    its client surface — the browser never installs Hub-side itself.
    """

    def load(self, *, all_issues: bool = False) -> BeadsLoad:
        """Fetch, default-fill, and sort beads issues via ``bd``.

        A failure passes through as the reason to show; rows come back in board
        order, and the run carries the figures saying where its time went.
        """
        return BeadsLoader().run(all_issues=all_issues).in_board_order()
