"""Beads Browser — display beads issues in a Lux frame."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from punt_lux.apps._beads_payload import BeadsLoader, BeadsPayloadBuilder
from punt_lux.display_client import agent_element_factory
from punt_lux.protocol import Element, TextElement

if TYPE_CHECKING:
    from punt_lux.display_client import DisplayClient


class BeadsBrowser:
    """Fetch, format, and render beads issues as a Lux table."""

    def load(
        self, *, all_issues: bool = False
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Fetch, default-fill, filter, and sort beads issues via ``bd``.

        Returns ``(issues, error)``. On success, ``error`` is ``None`` and
        ``issues`` holds the sorted issue list (possibly empty). On any
        failure (timeout, non-zero exit, empty output, malformed JSON,
        unexpected JSON shape), ``issues`` is ``[]`` and ``error`` is a
        short human-readable reason.
        """
        issues, err = BeadsLoader().run(all_issues=all_issues)
        if err is not None:
            return [], err

        # Three-pass stable sort: updated_at desc, then priority asc, then
        # in_progress floats to top.
        issues.sort(key=lambda i: i.get("updated_at", ""), reverse=True)
        issues.sort(key=lambda i: i["priority"])
        issues.sort(key=lambda i: i["status"] != "in_progress")
        return issues, None

    def build_payload(self, issues: list[dict[str, Any]]) -> dict[str, Any]:
        """Build the show_table element dict and metadata for beads issues."""
        return BeadsPayloadBuilder().build(issues)

    def build_elements(
        self,
        result: tuple[list[dict[str, Any]], str | None],
    ) -> list[Element]:
        """Build display elements for a beads load result.

        Accepts the ``(issues, error)`` tuple returned by :meth:`load`.
        When ``error`` is set, returns a visible red error element instead
        of the "No active issues." placeholder — surfaces bd failures
        (timeout, non-zero exit, parse error) so the user sees the reason
        instead of a misleading empty frame.
        """
        issues, error = result
        if error is not None:
            return [
                TextElement(
                    id="bd-error",
                    content=f"bd unavailable — {error}",
                    color="#FF5555",
                )
            ]
        if not issues:
            return [TextElement(id="empty", content="No active issues.")]
        payload = self.build_payload(issues)
        table = agent_element_factory().element_from_dict(
            {
                "kind": "table",
                "id": "table",
                "columns": payload["columns"],
                "rows": payload["rows"],
                "flags": ["borders", "row_bg", "resizable", "sortable", "copy_id"],
                "filters": payload["filters"],
                "detail": payload["detail"],
            }
        )
        return [table]

    def render(self, client: DisplayClient) -> None:
        """Send the beads issue board to the display via *client*."""
        project = Path.cwd().name or "unknown"
        frame_id = f"beads-{project}"
        client.show_async(
            f"beads-{project}",
            elements=self.build_elements(self.load()),
            frame_id=frame_id,
            frame_title=f"Beads: {project}",
        )
