"""How a daemon session is named and shown in the Hub."""

from __future__ import annotations

from typing import Self

from punt_lux.pty.listed_session import ListedSession
from punt_lux.wire.operations import RenderRequest


class TerminalScenes:
    """Own the scene and frame naming of terminal windows.

    A session's scene and frame are both ``terminal-<id>``. Ids are never
    reused by the daemon, so a name never denotes two sessions.
    """

    _prefix: str

    def __new__(cls, prefix: str = "terminal-") -> Self:
        if not prefix:
            raise ValueError("terminal scene prefix is empty")
        self = super().__new__(cls)
        self._prefix = prefix
        return self

    def scene_id(self, session_id: str) -> str:
        """Return the scene (and frame) id of ``session_id``'s window."""
        return f"{self._prefix}{session_id}"

    def owns(self, scene_id: str) -> bool:
        """Say whether ``scene_id`` names a terminal window."""
        return scene_id.startswith(self._prefix) and len(scene_id) > len(self._prefix)

    def session_of(self, scene_id: str) -> str:
        """Return the session id a terminal window's scene names.

        Raises:
            ValueError: ``scene_id`` is not a terminal window's scene.
        """
        if not self.owns(scene_id):
            raise ValueError(f"not a terminal scene: {scene_id}")
        return scene_id[len(self._prefix) :]

    def for_session(self, session: ListedSession) -> RenderRequest:
        """Return the request that shows ``session`` in its own window.

        The window title is the session's label.
        """
        shell: dict[str, object] = {
            "kind": "terminal",
            "id": "shell",
            "height": 0,
            "session": session.session,
        }
        return RenderRequest(
            scene_id=self.scene_id(session.session),
            title=session.label,
            elements=[shell],
        )
