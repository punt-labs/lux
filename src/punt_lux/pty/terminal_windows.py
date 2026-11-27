"""The terminal windows the helper has shown in the Hub, one scene per session."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.pty.listed_session import ListedSession
from punt_lux.pty.sync_plan import SyncPlan
from punt_lux.pty.terminal_scenes import TerminalScenes
from punt_lux.wire.operations import OpError

if TYPE_CHECKING:
    from punt_lux.pty.menu_clients import TerminalClients


class WindowRefusedError(RuntimeError):
    """The Hub could not show or remove one terminal's window."""


class TerminalWindows:
    """Show a window per session and take it down when the session ends.

    A window is a scene; the Display drops the frame with the scene. The Hub is
    the authority on what is shown, so ``refresh`` reads it before a reconcile.
    Only scenes owned by this helper's own identity count as its windows. A
    quarantined scene still counts: publishing it again resets the Hub's crash
    tally and ends the quarantine, so the window is left alone and cleared only
    when its session ends.
    """

    _clients: TerminalClients
    _scenes: TerminalScenes
    _shown: set[str]

    def __new__(cls, clients: TerminalClients) -> Self:
        self = super().__new__(cls)
        self._clients = clients
        self._scenes = TerminalScenes()
        self._shown = set()
        return self

    @property
    def shown(self) -> frozenset[str]:
        """The session ids with a window."""
        return frozenset(self._shown)

    async def refresh(self) -> None:
        """Learn which windows the Hub holds.

        Raises:
            WindowRefusedError: The Hub is unreachable or refused the query.
        """
        try:
            result = await self._clients.client().scene.ls()
        except OSError as error:
            raise WindowRefusedError(f"terminal windows unreadable: {error}") from error
        if isinstance(result, OpError):
            raise WindowRefusedError(f"terminal windows unreadable: {result.reason}")
        mine = self._clients.client().identity
        self._shown = {
            self._scenes.session_of(scene.local_id)
            for scene in result.scenes
            if self._scenes.owns(scene.local_id)
            and scene.owners
            and all(owner.identity == mine for owner in scene.owners)
        }

    async def open(self, session: ListedSession) -> None:
        """Show ``session`` in its own window; a window already shown stays.

        Raises:
            WindowRefusedError: The Hub is unreachable or refused the scene.
        """
        if session.session in self._shown:
            return
        request = self._scenes.for_session(session)
        try:
            result = await self._clients.client().scene.show(request)
        except OSError as error:
            raise self._failure("shown", session.session, str(error)) from error
        if isinstance(result, OpError):
            raise self._failure("shown", session.session, result.reason)
        self._shown.add(session.session)

    async def close(self, session_id: str) -> None:
        """Remove ``session_id``'s window and nothing else.

        Raises:
            WindowRefusedError: The Hub is unreachable or refused the removal.
        """
        if session_id not in self._shown:
            return
        scene = self._scenes.scene_id(session_id)
        try:
            result = await self._clients.client().scene.clear(scene)
        except OSError as error:
            raise self._failure("removed", session_id, str(error)) from error
        if isinstance(result, OpError):
            raise self._failure("removed", session_id, result.reason)
        self._shown.discard(session_id)

    async def clear(self) -> None:
        """Remove every window this helper shows, as it stops.

        Raises:
            WindowRefusedError: One or more windows could not be removed; it
                names each.
        """
        await self.apply(SyncPlan((), tuple(sorted(self._shown))))

    async def apply(self, plan: SyncPlan) -> None:
        """Open and close every window the plan names.

        A window the Hub refuses does not hold back the others.

        Raises:
            WindowRefusedError: One or more windows failed; it names each.
        """
        steps = (
            *(self.close(session_id) for session_id in plan.closed),
            *(self.open(session) for session in plan.opened),
        )
        failures: list[str] = []
        for step in steps:
            try:
                await step
            except WindowRefusedError as error:
                failures.append(str(error))
        if failures:
            raise WindowRefusedError("; ".join(failures))

    @staticmethod
    def _failure(what: str, session_id: str, reason: str) -> WindowRefusedError:
        return WindowRefusedError(f"terminal {session_id} not {what}: {reason}")
