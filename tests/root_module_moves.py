"""Removed single-file module paths and their package-owned replacements."""

from __future__ import annotations

MOVED_MODULES = {
    "punt_lux.__main__": "punt_lux.cli.__main__",
    **{
        f"punt_lux.{name}": f"punt_lux.kernel.{name}"
        for name in (
            "bounded_send",
            "client_host",
            "connection_identity",
            "connection_timing",
            "credentials",
            "log_level",
            "logging_config",
            "polled_event",
            "proctitle",
            "progress_clock",
            "repo_root",
            "runtime",
            "send_timeout",
            "socket_owner",
            "socket_writer",
            "tracing",
            "usage",
            "wire_queue",
            "write_progress",
        )
    },
    **{
        f"punt_lux.{name}": f"punt_lux.hub.{name}"
        for name in (
            "hub_composition",
            "hub_lifespan",
            "luxd",
            "mcp_endpoint",
            "mcp_session",
            "mcp_session_manager",
            "mcp_session_scope",
            "mcp_transport",
            "session_cleanup",
            "session_key",
            "transport_policy",
            "ws_listen",
            "ws_transport",
        )
    },
    "punt_lux.luxd_display": "punt_lux.display.luxd_display",
    "punt_lux.hook_cli": "punt_lux.cli.hook_cli",
    "punt_lux.pty.service": "punt_lux.service.terminal_service",
    "punt_lux.pty.enablement": "punt_lux.service.terminal_enablement",
}
