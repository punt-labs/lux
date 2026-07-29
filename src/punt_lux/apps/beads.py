"""Beads Browser — load beads issues and shape them into a display payload."""

from __future__ import annotations

from typing import Any

from punt_lux.apps._beads_payload import BeadsLoader, BeadsPayloadBuilder


class BeadsBrowser:
    """Fetch beads issues and shape their rows for display.

    The browser is the data provider a session runs from its own repo shell:
    ``load`` runs ``bd`` and ``build_payload`` shapes its rows. Request
    construction lives on ``BeadsBoard``, and the session pushes the result to the
    Hub through its client surface — the browser never installs Hub-side itself.
    """

    def load(
        self, *, all_issues: bool = False
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Fetch, default-fill, filter, and sort beads issues via ``bd``.

        Returns ``(issues, error)``: a sorted list and ``None`` on success, or
        ``[]`` and a short reason on any failure.
        """
        issues, err = BeadsLoader().run(all_issues=all_issues)
        if err is not None:
            return [], err

        # Three-pass stable sort: updated_at desc, priority asc, in_progress top.
        issues.sort(key=lambda i: i.get("updated_at", ""), reverse=True)
        issues.sort(key=lambda i: i["priority"])
        issues.sort(key=lambda i: i["status"] != "in_progress")
        return issues, None

    def build_payload(self, issues: list[dict[str, Any]]) -> dict[str, Any]:
        """Build the table columns/rows/filters/detail payload for beads issues."""
        return BeadsPayloadBuilder().build(issues)
