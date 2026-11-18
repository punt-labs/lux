"""Terminal output activity and Display idling policy, outside the render loop."""

from __future__ import annotations

import time

from imgui_bundle import hello_imgui

from punt_lux.display.terminal.sessions import TerminalSessions


class TerminalActivity:
    """Pump terminal output and keep the window awake while it is changing."""

    @staticmethod
    def pump() -> None:
        busy = TerminalSessions.pump_all()
        quiet_for = time.monotonic() - TerminalSessions.last_output_at
        hello_imgui.get_runner_params().fps_idling.enable_idling = (
            not busy and quiet_for > 0.25
        )

    @staticmethod
    def close() -> None:
        """Release local sessions on Display exit until the daemon replaces them."""
        TerminalSessions.close_all()
