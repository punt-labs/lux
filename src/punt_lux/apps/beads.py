"""Beads Browser — display beads issues in a Lux frame."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from punt_lux.apps._beads_payload import BeadsLoader, BeadsPayloadBuilder
from punt_lux.display_client import agent_element_factory
from punt_lux.protocol import Element, TextElement


class BeadsBrowser:
    """Fetch, format, and render beads issues as a Lux table."""

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
        """Build the show_table element dict and metadata for beads issues."""
        return BeadsPayloadBuilder().build(issues)

    def build_elements(
        self,
        result: tuple[list[dict[str, Any]], str | None],
    ) -> list[Element]:
        """Build display elements for the ``(issues, error)`` tuple from :meth:`load`.

        A set ``error`` yields a red error element, not the empty-frame placeholder.
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

    def render(self) -> None:
        """Install the beads board into the Hub; the replicator resends it.

        Imports are local to avoid a cycle with the Hub package.
        """
        from typing import cast

        from punt_lux.domain.element import Element as DomainElement
        from punt_lux.domain.hub import hub_display
        from punt_lux.domain.hub.replicator_instance import hub_replicator
        from punt_lux.domain.hub.scene_presentation import ScenePresentation
        from punt_lux.domain.ids import ConnectionId, SceneId

        project = Path.cwd().name or "unknown"
        scene_id = SceneId(f"beads-{project}")
        elements = cast("list[DomainElement]", self.build_elements(self.load()))
        # One write region: the roots and their frame land together, so the
        # replicator can never snapshot the new roots with a stale frame. show_scene
        # registers the connection as part of the replace, so no separate call.
        hub_display.show_scene(
            ConnectionId("app-beads"),
            scene_id,
            elements,
            ScenePresentation(frame_id=scene_id, frame_title=f"Beads: {project}"),
        )
        hub_replicator.mark_dirty(scene_id)
