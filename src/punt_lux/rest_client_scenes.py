"""The scene-family wire methods :class:`LuxRestClient` composes and delegates to.

Splits the largest cohesive cluster of REST verbs -- scene install, patch,
clear, list, inspect, and the table/dashboard composites -- out of
``rest_client.py`` so that module stays under its size target. Both classes
share one :class:`~punt_lux.rest_transport.HttpTransport` and one identity
header set; :class:`SceneRestOps` never constructs its own.

Every write method accepts (and ignores) a ``scope`` keyword to satisfy
:class:`~punt_lux.commands._ports.SceneOps`'s call signature -- the
in-process ``Operations`` facade that Protocol also serves needs the caller's
scope explicitly, but a REST request already composes its scope from the
``X-Lux-Client-*`` headers stamped on every call (``RestCaller.resolve``), so
the parameter here is structural conformance only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final
from urllib.parse import quote, urlencode

from punt_lux.operations import (
    Cleared,
    OpError,
    RenderDashboardRequest,
    RenderRequest,
    RenderTableRequest,
    SceneInspection,
    SceneList,
    SceneShown,
    UpdateRequest,
)
from punt_lux.rest_http_call import HttpCall
from punt_lux.rest_reply import RestReply

if TYPE_CHECKING:
    from punt_lux.operations import InspectScope, Scope
    from punt_lux.rest_transport import HttpTransport

__all__ = ["SceneRestOps"]


@final
class SceneRestOps:
    """Wraps the ``/scenes`` REST routes under one shared transport and headers."""

    _transport: HttpTransport
    _headers: dict[str, str]
    __slots__ = ("_headers", "_transport")

    def __new__(cls, transport: HttpTransport, headers: dict[str, str]) -> Self:
        self = super().__new__(cls)
        self._transport = transport
        self._headers = headers
        return self

    def render(
        self, request: RenderRequest | OpError, *, scope: Scope | None = None
    ) -> SceneShown | OpError:
        """Install a whole scene through ``PUT /scenes/{scene_id}``."""
        del scope  # REST composes scope from headers, not this parameter
        if isinstance(request, OpError):
            return request
        segment = quote(request.scene_id, safe="")
        return self._send(HttpCall.write(f"/scenes/{segment}", request, self._headers))

    def render_table(
        self, request: RenderTableRequest | OpError, *, scope: Scope | None = None
    ) -> SceneShown | OpError:
        """Install a composed table scene through ``PUT /scenes/{scene_id}/table``."""
        del scope
        if isinstance(request, OpError):
            return request
        segment = quote(request.scene_id, safe="")
        path = f"/scenes/{segment}/table"
        return self._send(HttpCall.write(path, request, self._headers))

    def render_dashboard(
        self, request: RenderDashboardRequest | OpError, *, scope: Scope
    ) -> SceneShown | OpError:
        """Construct a dashboard scene through ``PUT /scenes/{scene_id}/dashboard``."""
        del scope
        if isinstance(request, OpError):
            return request
        segment = quote(request.scene_id, safe="")
        path = f"/scenes/{segment}/dashboard"
        return self._send(HttpCall.write(path, request, self._headers))

    def update(
        self, scene_id: str, request: UpdateRequest | OpError, *, scope: Scope
    ) -> SceneShown | OpError:
        """Apply a patch batch through ``PATCH /scenes/{scene_id}``."""
        del scope
        if isinstance(request, OpError):
            return request
        segment = quote(scene_id, safe="")
        call = HttpCall.patch(f"/scenes/{segment}", request, self._headers)
        return self._send(call)

    def clear(self, *, scope: Scope) -> Cleared | OpError:
        """Clear every scene this identity owns through ``DELETE /scenes``."""
        del scope
        call = HttpCall.delete("/scenes", self._headers)
        return RestReply(self._transport.request(call)).read(Cleared)

    def clear_scene(self, *, scope: Scope, scene_id: str) -> Cleared | OpError:
        """Clear one scene through ``DELETE /scenes/{scene_id}``."""
        del scope
        segment = quote(scene_id, safe="")
        call = HttpCall.delete(f"/scenes/{segment}", self._headers)
        return RestReply(self._transport.request(call)).read(Cleared)

    def list_scenes(self) -> SceneList:
        """List every live scene and frame through ``GET /scenes``.

        ``SceneOps.list_scenes`` promises a ``SceneList`` with no error case
        (the in-process ``Operations`` facade this Protocol also serves never
        fails this read); a REST-level fault is a genuine surprise, so it is
        raised rather than returned (PY-EH-8).
        """
        call = HttpCall.read("/scenes", self._headers)
        result = RestReply(self._transport.request(call)).read(SceneList)
        if isinstance(result, OpError):
            raise RuntimeError(f"list_scenes failed: {result.reason}")
        return result

    def inspect_scene(
        self, scene_id: str, *, scope: Scope, facts: InspectScope
    ) -> SceneInspection | OpError:
        """Return the caller's own scene tree through ``GET /scenes/{scene_id}``."""
        del scope
        segment = quote(scene_id, safe="")
        query = urlencode({"want_geometry": facts.want_geometry})
        call = HttpCall.read(f"/scenes/{segment}?{query}", self._headers)
        return RestReply(self._transport.request(call)).read(SceneInspection)

    def _send(self, call: HttpCall) -> SceneShown | OpError:
        """Send a scene-write call and read its reply as a ``SceneShown`` or error."""
        return RestReply(self._transport.request(call)).read(SceneShown)
