"""Request/response messages — introspect, list scenes, screenshot, query."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

__all__ = [
    "IntrospectRequest",
    "IntrospectResponse",
    "ListScenesRequest",
    "ListScenesResponse",
    "QueryRequest",
    "QueryResponse",
    "ScreenshotRequest",
    "ScreenshotResponse",
    "register_codecs",
]


@dataclass(frozen=True, slots=True)
class IntrospectRequest:
    """Request the element tree for a scene."""

    scene_id: str
    type: Literal["introspect_request"] = "introspect_request"


@dataclass(frozen=True, slots=True)
class IntrospectResponse:
    """Response with the scene's element tree."""

    scene_id: str
    elements: list[dict[str, Any]] = field(
        default_factory=lambda: list[dict[str, Any]]()
    )
    type: Literal["introspect_response"] = "introspect_response"
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ListScenesRequest:
    """Request the list of active scenes and frames."""

    type: Literal["list_scenes_request"] = "list_scenes_request"


@dataclass(frozen=True, slots=True)
class ListScenesResponse:
    """Response with active scenes and frames."""

    scenes: list[dict[str, Any]] = field(default_factory=lambda: list[dict[str, Any]]())
    frames: list[dict[str, Any]] = field(default_factory=lambda: list[dict[str, Any]]())
    type: Literal["list_scenes_response"] = "list_scenes_response"


@dataclass(frozen=True, slots=True)
class ScreenshotRequest:
    """Request a screenshot of the current display."""

    type: Literal["screenshot_request"] = "screenshot_request"


@dataclass(frozen=True, slots=True)
class ScreenshotResponse:
    """Response with path to the captured screenshot."""

    path: str = ""
    type: Literal["screenshot_response"] = "screenshot_response"
    error: str | None = None


@dataclass(frozen=True, slots=True)
class QueryRequest:
    """Generic introspection/control request."""

    method: str
    params: dict[str, Any] = field(default_factory=lambda: dict[str, Any]())
    type: Literal["query_request"] = "query_request"


@dataclass(frozen=True, slots=True)
class QueryResponse:
    """Generic introspection/control response."""

    method: str
    result: dict[str, Any] = field(default_factory=lambda: dict[str, Any]())
    type: Literal["query_response"] = "query_response"
    error: str | None = None


def _introspect_request_to_dict(m: IntrospectRequest) -> dict[str, Any]:
    return {"type": m.type, "scene_id": m.scene_id}


def _introspect_response_to_dict(m: IntrospectResponse) -> dict[str, Any]:
    d: dict[str, Any] = {
        "type": m.type,
        "scene_id": m.scene_id,
        "elements": m.elements,
    }
    if m.error is not None:
        d["error"] = m.error
    return d


def _list_scenes_request_to_dict(m: ListScenesRequest) -> dict[str, Any]:
    return {"type": m.type}


def _list_scenes_response_to_dict(m: ListScenesResponse) -> dict[str, Any]:
    return {"type": m.type, "scenes": m.scenes, "frames": m.frames}


def _screenshot_request_to_dict(m: ScreenshotRequest) -> dict[str, Any]:
    return {"type": m.type}


def _screenshot_response_to_dict(m: ScreenshotResponse) -> dict[str, Any]:
    d: dict[str, Any] = {"type": m.type, "path": m.path}
    if m.error is not None:
        d["error"] = m.error
    return d


def _query_request_to_dict(m: QueryRequest) -> dict[str, Any]:
    d: dict[str, Any] = {"type": m.type, "method": m.method}
    if m.params:
        d["params"] = m.params
    return d


def _query_response_to_dict(m: QueryResponse) -> dict[str, Any]:
    d: dict[str, Any] = {"type": m.type, "method": m.method, "result": m.result}
    if m.error is not None:
        d["error"] = m.error
    return d


def _introspect_request_from_dict(d: dict[str, Any]) -> IntrospectRequest:
    return IntrospectRequest(scene_id=d["scene_id"])


def _introspect_response_from_dict(d: dict[str, Any]) -> IntrospectResponse:
    return IntrospectResponse(
        scene_id=d["scene_id"],
        elements=d.get("elements", []),
        error=d.get("error"),
    )


def _list_scenes_request_from_dict(_d: dict[str, Any]) -> ListScenesRequest:
    return ListScenesRequest()


def _list_scenes_response_from_dict(d: dict[str, Any]) -> ListScenesResponse:
    return ListScenesResponse(scenes=d.get("scenes", []), frames=d.get("frames", []))


def _screenshot_request_from_dict(_d: dict[str, Any]) -> ScreenshotRequest:
    return ScreenshotRequest()


def _screenshot_response_from_dict(d: dict[str, Any]) -> ScreenshotResponse:
    return ScreenshotResponse(
        path=d.get("path", ""),
        error=d.get("error"),
    )


def _query_request_from_dict(d: dict[str, Any]) -> QueryRequest:
    return QueryRequest(method=d["method"], params=d.get("params", {}))


def _query_response_from_dict(d: dict[str, Any]) -> QueryResponse:
    return QueryResponse(
        method=d["method"],
        result=d.get("result", {}),
        error=d.get("error"),
    )


_Register = Callable[
    [str, type, Callable[..., dict[str, Any]], Callable[[dict[str, Any]], Any]],
    None,
]


def register_codecs(register: _Register) -> None:
    """Register this module's message codecs into a MessageRegistry."""
    register(
        "introspect_request",
        IntrospectRequest,
        _introspect_request_to_dict,
        _introspect_request_from_dict,
    )
    register(
        "introspect_response",
        IntrospectResponse,
        _introspect_response_to_dict,
        _introspect_response_from_dict,
    )
    register(
        "list_scenes_request",
        ListScenesRequest,
        _list_scenes_request_to_dict,
        _list_scenes_request_from_dict,
    )
    register(
        "list_scenes_response",
        ListScenesResponse,
        _list_scenes_response_to_dict,
        _list_scenes_response_from_dict,
    )
    register(
        "screenshot_request",
        ScreenshotRequest,
        _screenshot_request_to_dict,
        _screenshot_request_from_dict,
    )
    register(
        "screenshot_response",
        ScreenshotResponse,
        _screenshot_response_to_dict,
        _screenshot_response_from_dict,
    )
    register(
        "query_request", QueryRequest, _query_request_to_dict, _query_request_from_dict
    )
    register(
        "query_response",
        QueryResponse,
        _query_response_to_dict,
        _query_response_from_dict,
    )
