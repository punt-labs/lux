#!/usr/bin/env python3
"""Demo: multi-window dashboard with draw canvases and live controls.

Three draggable panels: a bar chart, a controls panel that drives it,
and a status monitor with a simple animated-style visualization.

Usage:
    uv run python demos/dashboard.py
"""

from __future__ import annotations

import math
import random
import time

from punt_lux.client import LuxClient
from punt_lux.protocol import (
    ButtonElement,
    CollapsingHeaderElement,
    ComboElement,
    DrawElement,
    GroupElement,
    InteractionMessage,
    Patch,
    SliderElement,
    TextElement,
    WindowElement,
)

BAR_COLORS = ["#4CAF50", "#2196F3", "#FF9800", "#E91E63", "#9C27B0"]
BAR_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri"]
INITIAL_VALUES = [65, 40, 80, 55, 70]


def _build_bar_chart(
    values: list[int],
    width: int = 320,
    height: int = 200,
) -> list[dict[str, object]]:
    """Generate draw commands for a horizontal bar chart."""
    commands: list[dict[str, object]] = []
    n = len(values)
    bar_h = (height - 20) / n
    padding = 4

    for i, val in enumerate(values):
        y_top = 10 + i * bar_h + padding
        y_bot = 10 + (i + 1) * bar_h - padding
        bar_w = (val / 100) * (width - 60)
        # Bar
        commands.append(
            {
                "cmd": "rect",
                "min": [50, y_top],
                "max": [50 + bar_w, y_bot],
                "color": BAR_COLORS[i % len(BAR_COLORS)],
                "filled": True,
                "rounding": 3.0,
            }
        )
        # Label
        commands.append(
            {
                "cmd": "text",
                "pos": [4, y_top + (y_bot - y_top) / 2 - 6],
                "text": BAR_LABELS[i],
                "color": "#CCCCCC",
            }
        )
        # Value
        commands.append(
            {
                "cmd": "text",
                "pos": [55 + bar_w, y_top + (y_bot - y_top) / 2 - 6],
                "text": str(val),
                "color": "#FFFFFF",
            }
        )
    return commands


def _build_gauge(
    value: float,
    width: int = 160,
    height: int = 160,
) -> list[dict[str, object]]:
    """Generate draw commands for a simple gauge arc approximation."""

    cx, cy = width / 2, height / 2 + 10
    r = min(width, height) / 2 - 20
    commands: list[dict[str, object]] = []

    # Background arc (series of line segments)
    segments = 30
    for i in range(segments):
        a1 = math.pi + (math.pi * i / segments)
        a2 = math.pi + (math.pi * (i + 1) / segments)
        commands.append(
            {
                "cmd": "line",
                "p1": [cx + r * math.cos(a1), cy + r * math.sin(a1)],
                "p2": [cx + r * math.cos(a2), cy + r * math.sin(a2)],
                "color": "#333333",
                "thickness": 6.0,
            }
        )

    # Value arc
    filled_segs = int(segments * (value / 100))
    color = "#4CAF50" if value < 70 else "#FF9800" if value < 90 else "#E91E63"
    for i in range(filled_segs):
        a1 = math.pi + (math.pi * i / segments)
        a2 = math.pi + (math.pi * (i + 1) / segments)
        commands.append(
            {
                "cmd": "line",
                "p1": [cx + r * math.cos(a1), cy + r * math.sin(a1)],
                "p2": [cx + r * math.cos(a2), cy + r * math.sin(a2)],
                "color": color,
                "thickness": 6.0,
            }
        )

    # Needle
    angle = math.pi + (math.pi * value / 100)
    needle_r = r - 15
    commands.append(
        {
            "cmd": "line",
            "p1": [cx, cy],
            "p2": [cx + needle_r * math.cos(angle), cy + needle_r * math.sin(angle)],
            "color": "#FFFFFF",
            "thickness": 2.0,
        }
    )
    # Center dot
    commands.append(
        {
            "cmd": "circle",
            "center": [cx, cy],
            "radius": 4,
            "color": "#FFFFFF",
            "filled": True,
        }
    )
    # Value text
    commands.append(
        {
            "cmd": "text",
            "pos": [cx - 12, cy + 15],
            "text": f"{value:.0f}%",
            "color": "#FFFFFF",
        }
    )

    return commands


def _build_scene(values: list[int], dataset: str) -> list[WindowElement | TextElement]:
    avg = sum(values) / len(values)
    return [
        # Chart window
        WindowElement(
            id="w-chart",
            title=f"Weekly Activity — {dataset}",
            x=20,
            y=20,
            width=360,
            height=260,
            children=[
                DrawElement(
                    id="bar-chart",
                    width=320,
                    height=200,
                    bg_color="#1A1A2E",
                    commands=_build_bar_chart(values),
                ),
            ],
        ),
        # Controls window
        WindowElement(
            id="w-controls",
            title="Controls",
            x=400,
            y=20,
            width=280,
            height=340,
            children=[
                ComboElement(
                    id="dataset",
                    label="Dataset",
                    items=["Team Alpha", "Team Beta", "Team Gamma"],
                    selected=["Team Alpha", "Team Beta", "Team Gamma"].index(dataset),
                ),
                CollapsingHeaderElement(
                    id="bars",
                    label="Bar Values",
                    default_open=True,
                    children=[
                        SliderElement(
                            id=f"bar-{i}",
                            label=BAR_LABELS[i],
                            value=float(values[i]),
                            min=0.0,
                            max=100.0,
                            integer=True,
                        )
                        for i in range(len(values))
                    ],
                ),
                GroupElement(
                    id="btn-row",
                    layout="columns",
                    children=[
                        ButtonElement(id="b-randomize", label="Randomize"),
                        ButtonElement(id="b-reset", label="Reset"),
                    ],
                ),
            ],
        ),
        # Gauge window
        WindowElement(
            id="w-gauge",
            title="Average",
            x=20,
            y=300,
            width=200,
            height=220,
            no_resize=True,
            children=[
                DrawElement(
                    id="gauge",
                    width=160,
                    height=160,
                    bg_color="#1A1A2E",
                    commands=_build_gauge(avg),
                ),
            ],
        ),
    ]


DATASETS: dict[str, list[int]] = {
    "Team Alpha": [65, 40, 80, 55, 70],
    "Team Beta": [30, 85, 45, 90, 60],
    "Team Gamma": [75, 50, 35, 65, 95],
}


def main() -> None:
    print("Connecting to Lux display server...")
    with LuxClient(auto_spawn=True, connect_timeout=10) as client:
        print("Connected! Sending dashboard scene...")

        values = list(INITIAL_VALUES)
        dataset = "Team Alpha"

        ack = client.show("dashboard", _build_scene(values, dataset))
        if ack:
            print(f"Scene acknowledged: {ack.scene_id}")
        else:
            print("Timeout waiting for ack")
            return

        print("\nAdjust sliders or switch datasets. Press Ctrl-C to quit.\n")

        try:
            while True:
                msg = client.recv(timeout=0.1)
                if msg is None:
                    continue
                if not isinstance(msg, InteractionMessage):
                    continue

                ts = time.strftime("%H:%M:%S")
                changed = False

                # Slider adjustments
                for i in range(len(values)):
                    if msg.element_id == f"bar-{i}" and msg.action == "changed":
                        values[i] = int(msg.value)
                        changed = True
                        print(f"[{ts}] {BAR_LABELS[i]}: {values[i]}")

                # Dataset switch
                if msg.element_id == "dataset" and msg.action == "changed":
                    val = msg.value
                    name = (
                        val.get("item", dataset) if isinstance(val, dict) else dataset
                    )
                    if name in DATASETS:
                        dataset = name
                        values = list(DATASETS[dataset])
                        changed = True
                        print(f"[{ts}] Switched to {dataset}: {values}")

                # Randomize
                if msg.element_id == "b-randomize":
                    values = [random.randint(10, 100) for _ in range(5)]
                    changed = True
                    print(f"[{ts}] Randomized: {values}")

                # Reset
                if msg.element_id == "b-reset":
                    values = list(DATASETS[dataset])
                    changed = True
                    print(f"[{ts}] Reset to {dataset} defaults")

                if changed:
                    avg = sum(values) / len(values)
                    client.update(
                        "dashboard",
                        [
                            Patch(
                                id="bar-chart",
                                set={"commands": _build_bar_chart(values)},
                            ),
                            Patch(
                                id="gauge",
                                set={"commands": _build_gauge(avg)},
                            ),
                            *[
                                Patch(id=f"bar-{i}", set={"value": float(values[i])})
                                for i in range(len(values))
                            ],
                        ],
                    )

        except KeyboardInterrupt:
            print("\nDone.")


if __name__ == "__main__":
    main()
