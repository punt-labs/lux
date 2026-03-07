#!/usr/bin/env python3
"""Demo: layout containers — group, tab_bar, collapsing_header, window.

Shows nested containers holding interactive widgets. Demonstrates
columns layout, tabbed content, collapsible sections, and movable
sub-windows — all composable and nestable.

Usage:
    uv run python demos/containers.py
"""

from __future__ import annotations

import time

from punt_lux.client import LuxClient
from punt_lux.protocol import (
    ButtonElement,
    CheckboxElement,
    CollapsingHeaderElement,
    ColorPickerElement,
    ComboElement,
    GroupElement,
    InputTextElement,
    InteractionMessage,
    SliderElement,
    TabBarElement,
    TextElement,
    WindowElement,
)

elements = [
    # --- Window 1: Settings panel with tabs ---
    WindowElement(
        id="w-settings",
        title="Settings",
        x=20,
        y=30,
        width=380,
        height=350,
        children=[
            TabBarElement(
                id="settings-tabs",
                tabs=[
                    {
                        "label": "Audio",
                        "children": [
                            SliderElement(
                                id="volume",
                                label="Volume",
                                value=75.0,
                                min=0.0,
                                max=100.0,
                                format="%.0f%%",
                            ),
                            CheckboxElement(id="mute", label="Mute"),
                            ComboElement(
                                id="output",
                                label="Output",
                                items=["Speakers", "Headphones", "HDMI"],
                            ),
                        ],
                    },
                    {
                        "label": "Display",
                        "children": [
                            ColorPickerElement(
                                id="bg-color",
                                label="Background",
                                value="#1A1A2E",
                            ),
                            SliderElement(
                                id="brightness",
                                label="Brightness",
                                value=80.0,
                                min=0.0,
                                max=100.0,
                            ),
                        ],
                    },
                    {
                        "label": "Profile",
                        "children": [
                            InputTextElement(
                                id="username",
                                label="Name",
                                hint="Enter name...",
                            ),
                            ComboElement(
                                id="role",
                                label="Role",
                                items=["Viewer", "Editor", "Admin"],
                            ),
                        ],
                    },
                ],
            ),
        ],
    ),
    # --- Window 2: Advanced with collapsing sections and column groups ---
    WindowElement(
        id="w-advanced",
        title="Advanced",
        x=420,
        y=30,
        width=350,
        height=300,
        children=[
            CollapsingHeaderElement(
                id="perf",
                label="Performance",
                default_open=True,
                children=[
                    SliderElement(
                        id="threads",
                        label="Threads",
                        value=4,
                        min=1,
                        max=16,
                        integer=True,
                    ),
                    CheckboxElement(id="debug", label="Debug mode"),
                ],
            ),
            CollapsingHeaderElement(
                id="actions",
                label="Actions",
                default_open=True,
                children=[
                    TextElement(
                        id="action-hint",
                        content="Side-by-side buttons via columns group:",
                        style="caption",
                    ),
                    GroupElement(
                        id="action-row",
                        layout="columns",
                        children=[
                            ButtonElement(id="b-apply", label="Apply"),
                            ButtonElement(id="b-reset", label="Reset"),
                            ButtonElement(id="b-export", label="Export"),
                        ],
                    ),
                ],
            ),
            CollapsingHeaderElement(
                id="about",
                label="About",
                children=[
                    TextElement(
                        id="about-text",
                        content="Lux v0.0.0 — layout containers demo",
                    ),
                ],
            ),
        ],
    ),
    # --- Window 3: small auto-sizing info window ---
    WindowElement(
        id="w-info",
        title="Info",
        x=420,
        y=350,
        width=200,
        height=100,
        auto_resize=True,
        children=[
            TextElement(
                id="info-text",
                content="Drag windows to rearrange.\nAll widgets are interactive.",
            ),
        ],
    ),
]


def main() -> None:
    print("Connecting to Lux display server...")
    with LuxClient(auto_spawn=True, connect_timeout=10) as client:
        print("Connected! Sending layout containers scene...")
        ack = client.show("demo-containers", elements, title="Lux Layout Containers")
        if ack:
            print(f"Scene acknowledged: {ack.scene_id}")
        else:
            print("Timeout waiting for ack")
            return

        print("\nDrag the windows around. Interact with widgets.")
        print("Events will appear here. Press Ctrl-C to quit.\n")

        try:
            while True:
                msg = client.recv(timeout=0.5)
                if msg is None:
                    continue
                if isinstance(msg, InteractionMessage):
                    ts = time.strftime("%H:%M:%S")
                    print(
                        f"[{ts}] {msg.element_id}: "
                        f"action={msg.action}, value={msg.value}"
                    )
                else:
                    print(f"  other: {type(msg).__name__}")
        except KeyboardInterrupt:
            print("\nDone.")


if __name__ == "__main__":
    main()
