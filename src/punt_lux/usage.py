"""Declare and scope Lux's typed usage telemetry."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Self, final

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
_DEFAULT_CONFIG = TelemetryConfig()


@final
class _Usage:
    _active: Telemetry | None
    __slots__ = ("_active",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._active = None
        return self

    @contextmanager
    def open(self, config: TelemetryConfig = _DEFAULT_CONFIG) -> Generator[None]:
        """Own a daemon's telemetry for its lifetime, including bounded shutdown."""
        previous = self._active
        telemetry = open_telemetry("lux", _SCHEMAS, config)
        self._active = telemetry
        try:
            yield
        finally:
            self._active = previous
            telemetry.shutdown()

    def record_operation(self, name: str, elapsed_ms: float, *, failed: bool) -> None:
        """Record an allowlisted operation and outcome, never inputs or results."""
        telemetry = self._active
        if telemetry is not None:
            telemetry.record(
                _OPERATION_DURATION,
                1,
                elapsed_ms,
                operation=name,
                outcome="error" if failed else "ok",
            )

    def record_first_paint(self, elapsed_ms: float) -> None:
        """Record Display delivery latency without any scene identifiers."""
        telemetry = self._active
        if telemetry is not None:
            telemetry.record(_FIRST_PAINT_DURATION, 1, elapsed_ms)


_usage = _Usage()
capture_usage = _usage.open
record_operation = _usage.record_operation
record_first_paint = _usage.record_first_paint
