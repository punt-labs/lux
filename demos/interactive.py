#!/usr/bin/env python3
"""Demo: all interactive element kinds — sliders, checkboxes, combos, etc.

Launches the display server, sends a scene with every interactive
element, then prints interaction events as you manipulate them.

Usage:
    uv run python demos/interactive.py
"""

from __future__ import annotations

import time

from punt_lux.client import LuxClient
from punt_lux.protocol import (
    ButtonElement,
    CheckboxElement,
    ColorPickerElement,
    ComboElement,
    InputTextElement,
    InteractionMessage,
    RadioElement,
    SeparatorElement,
    SliderElement,
    TextElement,
)

elements = [
    TextElement(id="title", content="Interactive Elements Demo", style="heading"),
    SeparatorElement(),
    SliderElement(
        id="volume",
        label="Volume",
        value=50.0,
        min=0.0,
        max=100.0,
        format="%.0f%%",
    ),
    SliderElement(
        id="count",
        label="Count",
        value=5,
        min=1,
        max=20,
        integer=True,
    ),
    CheckboxElement(id="mute", label="Mute audio"),
    ComboElement(
        id="output",
        label="Output device",
        items=["Speakers", "Headphones", "Bluetooth", "HDMI"],
        selected=0,
    ),
    InputTextElement(id="name", label="Your name", hint="Enter name..."),
    RadioElement(
        id="quality",
        label="Quality",
        items=["Low", "Medium", "High", "Lossless"],
        selected=2,
    ),
    ColorPickerElement(id="accent", label="Accent color", value="#3399FF"),
    SeparatorElement(),
    ButtonElement(id="apply", label="Apply Settings"),
    ButtonElement(id="reset", label="Reset", action="reset"),
]


def main() -> None:
    print("Connecting to Lux display server...")
    with LuxClient(auto_spawn=True, connect_timeout=10) as client:
        print("Connected! Sending interactive scene...")
        ack = client.show("demo-interactive", elements, title="Lux Interactive Demo")
        if ack:
            print(f"Scene acknowledged: {ack.scene_id}")
        else:
            print("Timeout waiting for ack")
            return

        print("\nInteract with the elements in the window.")
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
