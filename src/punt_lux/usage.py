"""Declare and scope Lux's typed usage telemetry."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from punt_observe.telemetry import (
    EnumAttr,
    SignalSchema,
    TelemetryConfig,
    open_telemetry,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from punt_observe.telemetry import Telemetry

_OPERATION_DURATION = "lux.hub.operation_duration"
_FIRST_PAINT_DURATION = "lux.display.first_paint_duration"
_SCHEMAS = (
    SignalSchema(
        _OPERATION_DURATION,
        1,
        "histogram",
        {
            "operation": EnumAttr(
                (
                    "render",
                    "update",
                    "clear",
                    "clear_scene",
                    "render_table",
                    "render_dashboard",
                    "list_frames",
                    "remove_frame",
                    "set_menu",
                    "register_callback",
                    "show_client_details",
                )
            ),
            "outcome": EnumAttr(("ok", "error")),
        },
        unit="ms",
    ),
    SignalSchema(_FIRST_PAINT_DURATION, 1, "histogram", {}, unit="ms"),
)
_active_telemetry: Telemetry | None = None
_DEFAULT_CONFIG = TelemetryConfig()


@contextmanager
def capture_usage(config: TelemetryConfig = _DEFAULT_CONFIG) -> Generator[None]:
    """Own a daemon's telemetry for its lifetime, including bounded shutdown."""
    global _active_telemetry
    previous = _active_telemetry
    telemetry = open_telemetry("lux", _SCHEMAS, config)
    _active_telemetry = telemetry
    try:
        yield
    finally:
        _active_telemetry = previous
        telemetry.shutdown()


def record_operation(name: str, elapsed_ms: float, *, failed: bool) -> None:
    """Record an allowlisted operation and outcome, never its inputs or result."""
    telemetry = _active_telemetry
    if telemetry is not None:
        telemetry.record(
            _OPERATION_DURATION,
            1,
            elapsed_ms,
            operation=name,
            outcome="error" if failed else "ok",
        )


def record_first_paint(elapsed_ms: float) -> None:
    """Record Display delivery latency without any scene identifiers."""
    telemetry = _active_telemetry
    if telemetry is not None:
        telemetry.record(_FIRST_PAINT_DURATION, 1, elapsed_ms)
