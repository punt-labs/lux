"""BeadsBoard — turn a beads load result into the request that displays it."""

from __future__ import annotations

from typing import Any, Self, final

from punt_lux.apps._beads_payload import BeadsPayloadBuilder
from punt_lux.operations import RenderRequest, RenderTableRequest
from punt_lux.operations.models.render import FrameSpec
from punt_lux.protocol import TextElement

# The board's table flags: borders and row striping, plus resize, sort, and
# copy-id — the same chrome the board carried before the table route.
_BOARD_FLAGS = ["borders", "row_bg", "resizable", "sortable", "copy_id"]


@final
class BeadsBoard:
    """A named beads board: it renders a load result into the request that shows it.

    Issues become a table the Hub composes with live chrome — search, status and
    type combos, a selection-bound detail panel — sent as data through the table
    route, not a pre-composed tree. An error or empty board becomes a
    one-text-element message scene, which has no handlers to lose to the wire
    decode. Both render into the frame this board names.
    """

    _scene_id: str
    _title: str
    __slots__ = ("_scene_id", "_title")

    def __new__(cls, scene_id: str, title: str) -> Self:
        self = super().__new__(cls)
        self._scene_id = scene_id
        self._title = title
        return self

    @classmethod
    def for_project(cls, project: str) -> Self:
        """The one beads board of a repository, by the name every surface uses.

        A repository has one board, not one per surface: the ``lux show beads``
        command, the post-``bd`` refresh, and a session's menu entry all name this
        scene, so a refresh from any of them lands in the tab the user is already
        looking at rather than opening a second identical one. A scene is replaced
        wholesale by its latest show whoever owns it, so the last surface to
        refresh simply owns it.
        """
        return cls(f"beads-{project}", f"Beads: {project}")

    def request(
        self, result: tuple[list[dict[str, Any]], str | None]
    ) -> RenderTableRequest | RenderRequest:
        """Build the request that displays a ``(issues, error)`` load result.

        A set error yields a red message; an empty board yields the placeholder
        message; issues yield a table the Hub composes with live chrome.
        """
        issues, error = result
        if error is not None:
            return self.failure(f"bd unavailable — {error}")
        if not issues:
            return self._message(TextElement(id="empty", content="No active issues."))
        payload = BeadsPayloadBuilder().build(issues)
        return RenderTableRequest(
            scene_id=self._scene_id,
            columns=payload["columns"],
            rows=payload["rows"],
            filters=payload["filters"],
            detail=payload["detail"],
            flags=_BOARD_FLAGS,
            title=self._title,
            frame_id=self._scene_id,
            frame_title=self._title,
        )

    def failure(self, reason: str) -> RenderRequest:
        """Return a red message scene reporting why the board could not be shown."""
        return self._message(
            TextElement(id="beads-error", content=reason, color="#FF5555")
        )

    def _message(self, element: TextElement) -> RenderRequest:
        """Wrap a single text element as a one-element scene in the board's frame."""
        return RenderRequest(
            scene_id=self._scene_id,
            elements=[element.to_dict()],
            title=self._title,
            frame=FrameSpec(frame_id=self._scene_id, frame_title=self._title),
        )
