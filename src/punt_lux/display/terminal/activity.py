"""Terminal output activity and Display idling policy, outside the render loop."""

from __future__ import annotations

from imgui_bundle import hello_imgui

from punt_lux.display.terminal.remote_sessions import RemoteSessions


class TerminalActivity:
    """Pump terminal output and keep the window awake while it is changing."""

    @staticmethod
    def pump() -> None:
        hello_imgui.get_runner_params().fps_idling.enable_idling = (
            RemoteSessions.pump_frame().should_idle
        )

    @staticmethod
    def close() -> None:
        """Release replicas and connection; the daemon keeps its programs."""
        RemoteSessions.close_all()
