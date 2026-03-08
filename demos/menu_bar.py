#!/usr/bin/env python3
"""Demo: Pharo-inspired menu bar with agent-extensible custom menus.

Showcases the menu bar feature (Phase 3.5). The display provides built-in
menus (Theme, Window, Lux) automatically. This demo adds custom agent
menus that control a multi-window workspace:

  Tools  — Generate data, clear the log, reset the workspace
  View   — Toggle visibility of individual panels

Each menu click emits an InteractionMessage that the event loop handles
to update the scene. The workspace has three windows:

  Chart   — bar chart drawn on a DrawElement canvas
  Log     — scrollable event log via SelectableElement
  Status  — live counters (events seen, active panels, uptime)

Usage:
    uv run python demos/menu_bar.py
"""

from __future__ import annotations

import random
import time
from typing import Any

from punt_lux.client import LuxClient
from punt_lux.protocol import (
    ButtonElement,
    DrawElement,
    GroupElement,
    InteractionMessage,
    ProgressElement,
    SelectableElement,
    SeparatorElement,
    TextElement,
    WindowElement,
)

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

BAR_COLORS = ["#4CAF50", "#2196F3", "#FF9800", "#E91E63", "#9C27B0", "#00BCD4"]
BAR_LABELS = ["Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta"]


class AppState:
    """Mutable application state driving the scene."""

    def __init__(self) -> None:
        self.values: list[int] = [random.randint(20, 95) for _ in range(6)]
        self.log: list[str] = ["Session started"]
        self.show_chart = True
        self.show_log = True
        self.show_status = True
        self.event_count = 0
        self.start_time = time.monotonic()

    def randomize(self) -> None:
        self.values = [random.randint(10, 100) for _ in range(6)]
        self.log_event("Generated new data")

    def log_event(self, text: str) -> None:
        ts = time.strftime("%H:%M:%S")
        self.log.append(f"[{ts}] {text}")
        if len(self.log) > 20:
            self.log = self.log[-20:]

    def clear_log(self) -> None:
        self.log = ["Log cleared"]

    def reset(self) -> None:
        self.__init__()  # type: ignore[misc]

    @property
    def uptime(self) -> str:
        elapsed = int(time.monotonic() - self.start_time)
        m, s = divmod(elapsed, 60)
        return f"{m:02d}:{s:02d}"

    @property
    def active_panels(self) -> int:
        return sum([self.show_chart, self.show_log, self.show_status])


# ---------------------------------------------------------------------------
# Scene builders
# ---------------------------------------------------------------------------


def _build_bar_commands(values: list[int]) -> list[dict[str, Any]]:
    """Build draw commands for a horizontal bar chart."""
    commands: list[dict[str, Any]] = []
    bar_h = 22
    gap = 6
    max_val = max(values) if values else 1
    chart_w = 260

    for i, val in enumerate(values):
        y = i * (bar_h + gap) + 10
        w = int((val / max_val) * chart_w)

        # bar
        commands.append(
            {
                "cmd": "rect",
                "min": [10, y],
                "max": [10 + w, y + bar_h],
                "color": BAR_COLORS[i % len(BAR_COLORS)],
                "filled": True,
            }
        )
        # label
        commands.append(
            {
                "cmd": "text",
                "pos": [15 + w, y + 4],
                "text": f"{BAR_LABELS[i]} ({val})",
                "color": "#CCCCCC",
            }
        )

    return commands


def _build_chart_window(state: AppState) -> WindowElement:
    chart_h = len(state.values) * 28 + 20
    return WindowElement(
        id="w-chart",
        title="Chart",
        x=20,
        y=40,
        width=420,
        height=float(chart_h + 80),
        children=[
            DrawElement(
                id="bar-canvas",
                width=400,
                height=chart_h,
                bg_color="#1E1E2E",
                commands=_build_bar_commands(state.values),
            ),
            SeparatorElement(),
            GroupElement(
                id="chart-btns",
                layout="columns",
                children=[
                    ButtonElement(id="btn-randomize", label="Randomize"),
                    ButtonElement(id="btn-sort-asc", label="Sort Asc"),
                    ButtonElement(id="btn-sort-desc", label="Sort Desc"),
                ],
            ),
        ],
    )


def _build_log_window(state: AppState) -> WindowElement:
    log_items = [
        SelectableElement(id=f"log-{i}", label=entry)
        for i, entry in enumerate(state.log)
    ]
    return WindowElement(
        id="w-log",
        title="Event Log",
        x=450,
        y=40,
        width=330,
        height=250,
        children=[
            TextElement(
                id="log-count",
                content=f"{len(state.log)} entries",
                style="caption",
            ),
            SeparatorElement(),
            *log_items,
        ],
    )


def _build_status_window(state: AppState) -> WindowElement:
    progress_val = min(1.0, state.event_count / 50.0)
    return WindowElement(
        id="w-status",
        title="Status",
        x=450,
        y=310,
        width=330,
        height=200,
        children=[
            TextElement(
                id="stat-events",
                content=f"Events processed: {state.event_count}",
            ),
            TextElement(
                id="stat-panels",
                content=f"Active panels: {state.active_panels}/3",
            ),
            TextElement(
                id="stat-uptime",
                content=f"Uptime: {state.uptime}",
            ),
            SeparatorElement(),
            TextElement(id="stat-progress-label", content="Event milestone (50):"),
            ProgressElement(
                id="stat-progress",
                fraction=progress_val,
                label=f"{state.event_count}/50",
            ),
        ],
    )


def build_scene(state: AppState) -> list[Any]:
    """Build the full scene from current state."""
    elements: list[Any] = []
    if state.show_chart:
        elements.append(_build_chart_window(state))
    if state.show_log:
        elements.append(_build_log_window(state))
    if state.show_status:
        elements.append(_build_status_window(state))
    if not elements:
        elements.append(
            TextElement(
                id="empty-msg",
                content="All panels hidden. Use View menu to show them.",
                style="caption",
            )
        )
    return elements


# ---------------------------------------------------------------------------
# Menu definition
# ---------------------------------------------------------------------------

MENUS: list[dict[str, Any]] = [
    {
        "label": "Tools",
        "items": [
            {"label": "Generate Data", "id": "menu-generate", "shortcut": "Ctrl+G"},
            {"label": "Sort Ascending", "id": "menu-sort-asc"},
            {"label": "Sort Descending", "id": "menu-sort-desc"},
            {"label": "---"},
            {"label": "Clear Log", "id": "menu-clear-log"},
            {"label": "---"},
            {"label": "Reset Workspace", "id": "menu-reset", "shortcut": "Ctrl+R"},
        ],
    },
    {
        "label": "View",
        "items": [
            {"label": "Toggle Chart", "id": "menu-toggle-chart"},
            {"label": "Toggle Log", "id": "menu-toggle-log"},
            {"label": "Toggle Status", "id": "menu-toggle-status"},
        ],
    },
]


# ---------------------------------------------------------------------------
# Event handling
# ---------------------------------------------------------------------------


def handle_event(msg: InteractionMessage, state: AppState) -> bool:
    """Handle an interaction. Returns True if scene needs refresh."""
    state.event_count += 1
    eid = msg.element_id
    action = msg.action

    # -- button clicks --
    if action in ("click", "btn-randomize") or eid == "btn-randomize":
        state.randomize()
        return True

    if eid == "btn-sort-asc":
        state.values.sort()
        state.log_event("Sorted ascending")
        return True

    if eid == "btn-sort-desc":
        state.values.sort(reverse=True)
        state.log_event("Sorted descending")
        return True

    # -- menu clicks --
    if action == "menu":
        return _handle_menu(eid, state)

    # -- log selection --
    if eid.startswith("log-") and action == "clicked":
        state.log_event(f"Selected log entry #{eid}")
        return True

    return False


def _handle_menu(menu_id: str, state: AppState) -> bool:
    if menu_id == "menu-generate":
        state.randomize()
        return True
    if menu_id == "menu-sort-asc":
        state.values.sort()
        state.log_event("Sorted ascending (menu)")
        return True
    if menu_id == "menu-sort-desc":
        state.values.sort(reverse=True)
        state.log_event("Sorted descending (menu)")
        return True
    if menu_id == "menu-clear-log":
        state.clear_log()
        return True
    if menu_id == "menu-reset":
        state.reset()
        return True
    if menu_id == "menu-toggle-chart":
        state.show_chart = not state.show_chart
        state.log_event(f"Chart {'shown' if state.show_chart else 'hidden'}")
        return True
    if menu_id == "menu-toggle-log":
        state.show_log = not state.show_log
        state.log_event(f"Log {'shown' if state.show_log else 'hidden'}")
        return True
    if menu_id == "menu-toggle-status":
        state.show_status = not state.show_status
        state.log_event(f"Status {'shown' if state.show_status else 'hidden'}")
        return True
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    print("Connecting to Lux display server...")
    with LuxClient(auto_spawn=True, connect_timeout=10) as client:
        print("Connected!")

        state = AppState()

        # Set agent menus (these appear alongside built-in Theme/Window/Lux menus)
        client.set_menu(MENUS)
        print("Custom menus installed: Tools, View")

        # Send initial scene
        ack = client.show("menu-demo", build_scene(state))
        if ack:
            print(f"Scene acknowledged: {ack.scene_id}")
        else:
            print("Timeout waiting for ack")
            return

        print("\nTry the menu bar: Theme, Tools, View.")
        print("Click buttons and log entries too. Ctrl-C to quit.\n")

        # Periodic status refresh
        last_refresh = time.monotonic()

        try:
            while True:
                msg = client.recv(timeout=0.1)

                # Process any received event first
                need_refresh = False
                if msg is not None and isinstance(msg, InteractionMessage):
                    ts = time.strftime("%H:%M:%S")
                    print(f"[{ts}] {msg.element_id}: {msg.action} = {msg.value}")
                    if handle_event(msg, state):
                        need_refresh = True

                # Refresh status panel every 2s (uptime counter)
                now = time.monotonic()
                if now - last_refresh > 2.0:
                    last_refresh = now
                    need_refresh = True

                if need_refresh:
                    client.show("menu-demo", build_scene(state))

        except KeyboardInterrupt:
            print(f"\nDone. Processed {state.event_count} events in {state.uptime}.")
        except (BrokenPipeError, ConnectionError, OSError):
            print("\nDisplay closed.")


if __name__ == "__main__":
    main()
