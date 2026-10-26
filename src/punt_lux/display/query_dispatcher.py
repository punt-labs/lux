"""Route QueryRequest messages to handler methods, and keep the display's log."""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Self

from punt_lux.display.display_log import DisplayLog
from punt_lux.display.scene_reports import SceneReports
from punt_lux.protocol import QueryResponse

if TYPE_CHECKING:
    from punt_lux.display.replica import SceneReplica

logger = logging.getLogger(__name__)


class QueryRouter:
    """Dispatch query requests to registered handlers.

    Registers the reports it can answer itself -- the scenes it was handed and its
    own log -- and takes every other handler from the object that owns the facts.
    No ImGui dependency: this is routing and the record of what went wrong.
    """

    _log: DisplayLog
    _query_handlers: dict[str, Callable[..., dict[str, Any]]]

    def __new__(cls, scenes: SceneReplica) -> Self:
        self = super().__new__(cls)
        self._log = DisplayLog()
        reports = SceneReports(scenes)
        self._query_handlers = {
            "list_scenes": reports.list_scenes,
            "display_state": reports.display_state,
            "list_recent_events": functools.partial(self._log.report, "events"),
            "list_errors": functools.partial(self._log.report, "errors"),
        }
        return self

    def register_handler(
        self, method: str, handler: Callable[..., dict[str, Any]]
    ) -> None:
        """Register the handler that answers a query method name."""
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
            self._log.record_error("error", str(exc), f"query:{method}")
            return QueryResponse(method=method, error=str(exc))

    def record_event(self, event: dict[str, Any]) -> None:
        """Append an event dict to the log for introspection."""
        self._log.record_event(event)

    def record_error(self, severity: str, message: str, context: str = "") -> None:
        """Record an error in the log for introspection."""
        self._log.record_error(severity, message, context)
