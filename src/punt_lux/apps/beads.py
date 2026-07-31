"""Beads Browser — load beads issues and shape them into a display payload."""

from __future__ import annotations

from typing import Any

from punt_lux.apps._beads_payload import BeadsLoader, BeadsPayloadBuilder
from punt_lux.apps.beads_result import BeadsFailure, BeadsResult, BeadsRows


class BeadsBrowser:
    """Fetch beads issues and shape their rows for display.

    The browser is the data provider a session runs from its own repo shell:
    ``load`` runs ``bd`` and ``build_payload`` shapes its rows. Request
    construction lives on ``BeadsBoard``, and the session pushes the result to the
    Hub through its client surface — the browser never installs Hub-side itself.
    """

    def load(self, *, all_issues: bool = False) -> BeadsResult:
        """Fetch, default-fill, and sort beads issues via ``bd``.

        A failure passes through as the reason to show; rows come back in board
        order. Sorting here rather than at the renderer keeps every surface that
        shows the board — command, hook, menu click — showing one order.
        """
        result = BeadsLoader().run(all_issues=all_issues)
        if isinstance(result, BeadsFailure):
            return result

        # Three-pass stable sort: updated_at desc, priority asc, in_progress top.
        issues = result.issues
        issues.sort(key=lambda i: i.get("updated_at", ""), reverse=True)
        issues.sort(key=lambda i: i["priority"])
        issues.sort(key=lambda i: i["status"] != "in_progress")
        return BeadsRows.of(issues)

    def build_payload(self, issues: list[dict[str, Any]]) -> dict[str, Any]:
        """Build the table columns/rows/filters/detail payload for beads issues."""
        return BeadsPayloadBuilder().build(issues)
