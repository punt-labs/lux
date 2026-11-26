"""A Hub that holds scenes in a dict, standing in for the REST boundary."""

from __future__ import annotations

import asyncio
from typing import Self, cast

from punt_lux.client.hub_client import CallbackHandler, ConnectHandler
from punt_lux.client.rest_transport import HubUnavailableError
from punt_lux.pty.menu_clients import TerminalClients
from punt_lux.wire.model.client_identity import ClientIdentity
from punt_lux.wire.operations import (
    Cleared,
    Ok,
    OpError,
    RenderRequest,
    SceneList,
    SceneShown,
)
from punt_lux.wire.operations.query_ownership import SceneOwner
from punt_lux.wire.operations.query_quarantine import QuarantineInfo
from punt_lux.wire.operations.query_scenes import SceneSummary


class StubListener:
    """A listen leg that connects once, delivers clicks, and never ends."""

    _callback: CallbackHandler
    _connected: ConnectHandler

    def __new__(cls, callback: CallbackHandler, connected: ConnectHandler) -> Self:
        self = super().__new__(cls)
        self._callback, self._connected = callback, connected
        return self

    async def click(self, callback: str) -> None:
        if (pending := self._callback(callback)) is not None:
            await pending

    async def listen(self) -> None:
        if (pending := self._connected()) is not None:
            await pending
        await asyncio.Event().wait()


class StubHub:
    """Show, clear and list scenes the way the Hub's operations answer.

    ``down`` makes every call fail as an unreachable Hub does; ``refuse`` makes
    ``show`` answer with an error instead of installing the scene.
    """

    _scenes: dict[str, RenderRequest]
    _foreign: set[str]
    _identity: ClientIdentity
    _menu: dict[str, str]
    _down: bool
    _refusal: str
    _refused: dict[str, str]
    _quarantined: set[str]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._scenes, self._menu, self._foreign = {}, {}, set()
        self._refused, self._quarantined = {}, set()
        self._identity = ClientIdentity(kind="app", name="luxd-pty", lease_ttl=30)
        self._down, self._refusal = False, ""
        return self

    @property
    def scenes(self) -> dict[str, RenderRequest]:
        return self._scenes

    @property
    def menu(self) -> dict[str, str]:
        return self._menu

    @property
    def clients(self) -> TerminalClients:
        """This hub, typed as the factory the helper takes."""
        return cast("TerminalClients", self)

    def client(self) -> Self:
        return self

    @property
    def scene(self) -> Self:
        return self

    def listener(
        self, callback: CallbackHandler, connected: ConnectHandler
    ) -> StubListener:
        return StubListener(callback, connected)

    @property
    def callback(self) -> Self:
        return self

    async def register(self, callback_id: str, label: str) -> Ok:
        self._require_up()
        self._menu[callback_id] = label
        return Ok()

    @property
    def identity(self) -> ClientIdentity:
        return self._identity

    @property
    def foreign(self) -> frozenset[str]:
        """Scene ids another connection owns; the helper can neither see nor clear."""
        return frozenset(self._foreign)

    def add_foreign(self, scene_id: str) -> None:
        """Install a scene owned by some other connection."""
        self._foreign.add(scene_id)

    def go_down(self) -> None:
        self._down = True

    def come_up(self, *, lose_scenes: bool = False) -> None:
        self._down = False
        if lose_scenes:
            self._scenes.clear()

    def refuse(self, reason: str) -> None:
        self._refusal = reason

    def quarantine(self, scene_id: str) -> None:
        """Hold ``scene_id`` out of display replication, as quarantine does."""
        self._quarantined.add(scene_id)

    def refuse_scene(self, scene_id: str, reason: str) -> None:
        """Refuse only the scene named ``scene_id``; others are shown."""
        self._refused[scene_id] = reason

    async def show(self, request: RenderRequest) -> SceneShown | OpError:
        self._require_up()
        if reason := self._refused.get(request.scene_id, self._refusal):
            return OpError(code="rejected", reason=reason)
        self._scenes[request.scene_id] = request
        return SceneShown(scene_id=request.scene_id)

    async def clear(self, scene_id: str) -> Cleared | OpError:
        self._require_up()
        self._scenes.pop(scene_id, None)
        return Cleared()

    async def ls(self) -> SceneList | OpError:
        self._require_up()
        mine = [SceneOwner(connection_id="mine", identity=self._identity)]
        theirs = [
            SceneOwner(
                connection_id="theirs",
                identity=ClientIdentity(kind="app", name="other"),
            )
        ]
        held = QuarantineInfo(death_count=3, last_death_at=1.0)
        rows = [
            SceneSummary(
                scene_id=f"hub:{name}",
                local_id=name,
                element_count=1,
                frame_id=name,
                owners=mine if name in self._scenes else theirs,
                status="quarantined" if name in self._quarantined else "live",
                quarantine=held if name in self._quarantined else None,
            )
            for name in [*self._scenes, *sorted(self._foreign)]
        ]
        return SceneList(scenes=rows, frames=[])

    def _require_up(self) -> None:
        if self._down:
            raise HubUnavailableError("Hub absent")
