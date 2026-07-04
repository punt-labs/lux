"""Route QueryRequest messages to handler methods, own event/error ring buffers."""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable
from typing import Any, Self

from punt_lux.protocol import QueryResponse
from punt_lux.scene import SceneManager

logger = logging.getLogger(__name__)


class QueryDispatcher:
    """Dispatch query requests to registered handlers.

    Owns the ring buffers for recent events and errors.  No ImGui
    dependency -- this is pure state management and routing.
    """

    _scene_manager: SceneManager
    _get_client_names: Callable[[], dict[int, str]]
    _get_client_connect_times: Callable[[], dict[int, float]]
    _get_menu_registrations: Callable[[], dict[int, list[dict[str, Any]]]]
    _get_agent_menus: Callable[[], list[dict[str, Any]]]
    _query_handlers: dict[str, Callable[..., dict[str, Any]]]
    _recent_events: deque[dict[str, Any]]
    _recent_errors: deque[dict[str, Any]]

    def __new__(
        cls,
        scene_manager: SceneManager,
        get_client_names: Callable[[], dict[int, str]],
        get_client_connect_times: Callable[[], dict[int, float]],
        get_menu_registrations: Callable[[], dict[int, list[dict[str, Any]]]],
        get_agent_menus: Callable[[], list[dict[str, Any]]],
    ) -> Self:
        self = super().__new__(cls)
        self._scene_manager = scene_manager
        self._get_client_names = get_client_names
        self._get_client_connect_times = get_client_connect_times
        self._get_menu_registrations = get_menu_registrations
        self._get_agent_menus = get_agent_menus

        self._query_handlers = {
            "list_scenes": self._query_list_scenes,
            "list_clients": self._query_list_clients,
            "list_menus": self._query_list_menus,
            "list_recent_events": self._query_list_recent_events,
            "list_errors": self._query_list_errors,
        }
        self._recent_events = deque(maxlen=200)
        self._recent_errors = deque(maxlen=100)
        return self

    # -- public API ------------------------------------------------------------

    def register_handler(
        self, method: str, handler: Callable[..., dict[str, Any]]
    ) -> None:
        """Register an external handler for a query method name."""
        self._query_handlers[method] = handler

    def handle_query(self, method: str, params: dict[str, Any] | None) -> QueryResponse:
        """Dispatch a query to the registered handler and return a response."""
        handler = self._query_handlers.get(method)
        if handler is None:
            return QueryResponse(method=method, error=f"Unknown method: {method}")
        try:
            result = handler(**(params or {}))
            return QueryResponse(method=method, result=result)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Query handler %s failed: %s", method, exc)
            self.record_error("error", str(exc), f"query:{method}")
            return QueryResponse(method=method, error=str(exc))

    def record_event(self, event: dict[str, Any]) -> None:
        """Append an event dict to the ring buffer for introspection."""
        self._recent_events.append(event)

    def record_error(self, severity: str, message: str, context: str = "") -> None:
        """Record an error in the ring buffer for introspection."""
        self._recent_errors.append(
            {
                "timestamp": time.time(),
                "severity": severity,
                "message": message,
                "context": context,
            }
        )

    # -- built-in query handlers -----------------------------------------------

    def _query_list_scenes(self, **_kwargs: Any) -> dict[str, Any]:
        """Query handler for list_scenes."""
        sm = self._scene_manager
        scenes: list[dict[str, Any]] = []
        for sid, scene in sm.scenes.items():
            scenes.append(
                {
                    "scene_id": sid,
                    "element_count": len(scene.elements),
                    "frame_id": sm.scene_to_frame.get(sid),
                    "owner_fd": sm.scene_to_owner.get(sid),
                }
            )
        for fid, frame in sm.frames.items():
            for sid, scene in frame.scenes.items():
                scenes.append(
                    {
                        "scene_id": sid,
                        "element_count": len(scene.elements),
                        "frame_id": fid,
                        "owner_fd": sm.scene_to_owner.get(sid),
                    }
                )
        frames: list[dict[str, Any]] = []
        for fid, frame in sm.frames.items():
            frame_scenes = [s for s, f in sm.scene_to_frame.items() if f == fid]
            frames.append(
                {
                    "frame_id": fid,
                    "title": frame.title,
                    "scene_count": len(frame_scenes),
                    "scene_ids": frame_scenes,
                    "layout": frame.layout,
                }
            )
        return {"scenes": scenes, "frames": frames}

    def _query_list_clients(self, **_kwargs: Any) -> dict[str, Any]:
        """Return list of connected clients."""
        now = time.time()
        client_names = self._get_client_names()
        connect_times = self._get_client_connect_times()
        menu_regs = self._get_menu_registrations()
        clients: list[dict[str, Any]] = []
        for fd, name in client_names.items():
            connected_at = connect_times.get(fd, now)
            menu_count = len(menu_regs.get(fd, []))
            clients.append(
                {
                    "connection_id": fd,
                    "name": name,
                    "connected_seconds": round(now - connected_at, 1),
                    "menu_item_count": menu_count,
                }
            )
        return {"clients": clients}

    def _query_list_menus(self, **_kwargs: Any) -> dict[str, Any]:
        """Return all registered menus and their items."""
        client_names = self._get_client_names()
        menu_regs = self._get_menu_registrations()
        menus: list[dict[str, Any]] = [
            {
                "id": item.get("id", ""),
                "label": item.get("label", ""),
                "shortcut": item.get("shortcut"),
                "owner_fd": fd,
                "owner_name": client_names.get(fd, f"fd={fd}"),
            }
            for fd, items in menu_regs.items()
            for item in items
        ]
        return {"menu_items": menus, "total": len(menus)}

    def _query_list_recent_events(
        self, count: int = 50, **_kwargs: Any
    ) -> dict[str, Any]:
        """Return the last N interaction events."""
        count = min(count, 200)
        events = list(self._recent_events)[-count:]
        return {
            "events": events,
            "total_buffered": len(self._recent_events),
        }

    def _query_list_errors(self, count: int = 20, **_kwargs: Any) -> dict[str, Any]:
        """Return the last N display-side errors."""
        count = min(count, 100)
        errors = list(self._recent_errors)[-count:]
        return {
            "errors": errors,
            "total_buffered": len(self._recent_errors),
        }
