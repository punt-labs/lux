"""A stub ``SceneOps`` shared by the scene command tests.

One class implementing every :class:`~punt_lux.commands.SceneOps` method, each
returning a canned result set at construction -- the humble-object test only
needs to supply the outcome its own command reads, per PL-TT-5.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, cast, final

from punt_lux.domain.hub.client_identity import ClientIdentity

if TYPE_CHECKING:
    from punt_lux.operations import (
        Cleared,
        InspectScope,
        OpError,
        RenderDashboardRequest,
        RenderRequest,
        RenderTableRequest,
        SceneInspection,
        SceneList,
        SceneShown,
        Scope,
        UpdateRequest,
    )


def identity() -> ClientIdentity:
    """Build a headless CLI identity -- no scene command reads it."""
    return ClientIdentity(kind="cli", name="test")


@final
class StubSceneOps:
    """A ``SceneOps`` stub returning one preset result per method.

    Each test constructs this with only the outcome its own command reads;
    the rest stay ``None`` -- structurally fine, since ``SceneOps`` requires
    every method to exist but no test ever calls more than one of them.

    The last call's routing args are recorded on ``last_call`` so a test can
    assert the command threaded ``scope``/``scene_id``/``request`` through
    correctly -- the adapter-routing bug class the humble-object pattern
    exists to catch.
    """

    # Each field is `| None`: a test supplies only the one outcome its
    # command reads (PY-TS-14) -- the others are never called.
    _show: SceneShown | OpError | None
    _clear: Cleared | OpError | None
    _inspect: SceneInspection | OpError | None
    _list: SceneList | None
    last_call: dict[str, object]
    __slots__ = ("_clear", "_inspect", "_list", "_show", "last_call")

    def __new__(
        cls,
        show: SceneShown | OpError | None = None,
        clear: Cleared | OpError | None = None,
        inspect: SceneInspection | OpError | None = None,
        scenes: SceneList | None = None,
    ) -> Self:
        self = super().__new__(cls)
        self._show = show
        self._clear = clear
        self._inspect = inspect
        self._list = scenes
        self.last_call = {}
        return self

    def render(
        self, request: RenderRequest | OpError, *, scope: Scope
    ) -> SceneShown | OpError:
        self.last_call = {"method": "render", "request": request, "scope": scope}
        return cast("SceneShown | OpError", self._show)

    def update(
        self, scene_id: str, request: UpdateRequest | OpError, *, scope: Scope
    ) -> SceneShown | OpError:
        self.last_call = {
            "method": "update",
            "scene_id": scene_id,
            "request": request,
            "scope": scope,
        }
        return cast("SceneShown | OpError", self._show)

    def clear_scene(self, *, scope: Scope, scene_id: str) -> Cleared | OpError:
        self.last_call = {
            "method": "clear_scene",
            "scene_id": scene_id,
            "scope": scope,
        }
        return cast("Cleared | OpError", self._clear)

    def clear(self, *, scope: Scope) -> Cleared | OpError:
        self.last_call = {"method": "clear", "scope": scope}
        return cast("Cleared | OpError", self._clear)

    def render_table(
        self, request: RenderTableRequest | OpError, *, scope: Scope
    ) -> SceneShown | OpError:
        self.last_call = {"method": "render_table", "request": request, "scope": scope}
        return cast("SceneShown | OpError", self._show)

    def render_dashboard(
        self, request: RenderDashboardRequest | OpError, *, scope: Scope
    ) -> SceneShown | OpError:
        self.last_call = {
            "method": "render_dashboard",
            "request": request,
            "scope": scope,
        }
        return cast("SceneShown | OpError", self._show)

    def inspect_scene(
        self, scene_id: str, *, scope: Scope, facts: InspectScope
    ) -> SceneInspection | OpError:
        self.last_call = {
            "method": "inspect_scene",
            "scene_id": scene_id,
            "scope": scope,
            "facts": facts,
        }
        return cast("SceneInspection | OpError", self._inspect)

    def list_scenes(self) -> SceneList:
        self.last_call = {"method": "list_scenes"}
        return cast("SceneList", self._list)
