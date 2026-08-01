"""BeadsBoard — turn a beads load result into the request that displays it."""

from __future__ import annotations

from typing import Self, final

from punt_lux.apps._beads_payload import BeadsPayloadBuilder
from punt_lux.apps.beads_result import BeadsFailure, BeadsResult
from punt_lux.operations import RenderRequest, RenderTableRequest
from punt_lux.operations.models.render import FrameSpec
from punt_lux.protocol import TextElement
from punt_lux.repo_root import RepoRoot

# The board's table flags: borders and row striping, plus resize, sort, and
# copy-id — the same chrome the board carried before the table route.
_BOARD_FLAGS = ["borders", "row_bg", "resizable", "sortable", "copy_id"]

# What a board belongs to when the process runs outside any repository: real and
# named, so a headless board has one home rather than one per directory.
_HEADLESS_PROJECT = "lux-session"


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

    @property
    def frame_id(self) -> str:
        """The frame this board renders into — the one a click asks to be raised.

        Every request this board builds names it, so a session can reach for the
        frame before it has any rows to put in it.
        """
        return self._scene_id

    @classmethod
    def for_repo(cls) -> Self:
        """The board of the repository this process runs in, named from its root.

        The name comes from the repository root rather than the working directory,
        so ``lux show beads`` from a subdirectory refreshes the repository's board
        instead of opening a second one named for that subdirectory. Both surfaces
        that open a board derive its name here, which is what makes the one-board
        promise above hold rather than depend on where each was started.
        """
        return cls.for_project(RepoRoot.of(_HEADLESS_PROJECT).name)

    def request(self, result: BeadsResult) -> RenderTableRequest | RenderRequest:
        """Build the request that displays a load result.

        Three outcomes, dispatched on the result itself: a failure yields a red
        message naming the reason, no rows yield the empty-board placeholder, and
        rows yield a table the Hub composes with live chrome.
        """
        if isinstance(result, BeadsFailure):
            return self.failure(f"bd unavailable — {result.reason}")
        if not result:
            return self._message(TextElement(id="empty", content="No active issues."))
        payload = BeadsPayloadBuilder().build(result.issues)
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

    def starting(self) -> RenderRequest:
        """Return the placeholder a click puts up before the issues have loaded.

        Reading the issues means a query to a hosted database, which takes as long
        as it takes; a user who clicked a menu item must not wait on it to see
        anything happen. This scene is what the frame opens with, and the loaded
        board replaces it in the same frame when the rows arrive.
        """
        return self._message(TextElement(id="beads-loading", content="Loading issues…"))

    def _message(self, element: TextElement) -> RenderRequest:
        """Wrap a single text element as a one-element scene in the board's frame."""
        return RenderRequest(
            scene_id=self._scene_id,
            elements=[element.to_dict()],
            title=self._title,
            frame=FrameSpec(frame_id=self._scene_id, frame_title=self._title),
        )
