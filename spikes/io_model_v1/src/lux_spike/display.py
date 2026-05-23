"""Display process — connects to Hub, decodes inbound Updates into its
own Element tree (rf=Text or Recording factory), runs a 10Hz render loop
that calls elem.render() each frame, reads stdin for simulated user input
that emits Interactions back to Hub.

Per io-model.md: Display has the render loop. ImGui-equivalent rendering
(here: TextOutput or RecordingLog) runs locally in this process. IPC
carries Updates and Events only — never render calls.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import TYPE_CHECKING

from lux_spike.codec import JsonElementFactory, encode_interaction
from lux_spike.connection import LineSocket, connect_unix, spawn_reader
from lux_spike.elements import ButtonElement, LabelElement, PanelElement
from lux_spike.renderers.recording import RecordingLog, RecordingRendererFactory
from lux_spike.renderers.text import TextOutput, TextRendererFactory
from lux_spike.updates import AddElement, InteractionMessage, SetProperty

if TYPE_CHECKING:
    from lux_spike.connection import WireDict
    from lux_spike.element import Element
    from lux_spike.protocols import RendererFactory


class DisplayDisplay:
    """Display-tier authoritative state owner. Holds the local Element tree.
    The render loop walks this tree every tick."""

    _by_id: dict[str, "Element"]
    _root: "Element | None"

    def __new__(cls) -> "DisplayDisplay":
        self = object.__new__(cls)
        self._by_id = {}
        self._root = None
        return self

    def apply(self, update: AddElement | SetProperty) -> None:
        match update:
            case AddElement(elem=elem, parent_id=parent_id):
                self._index(elem)
                if parent_id is None:
                    self._root = elem
            case SetProperty(elem_id=eid, field=field, value=value):
                elem = self._by_id.get(eid)
                if elem is None:
                    return
                if isinstance(elem, LabelElement) and field == "content":
                    elem._set_content(str(value))

    def _index(self, elem: "Element") -> None:
        if isinstance(elem, LabelElement | ButtonElement | PanelElement):
            self._by_id[elem.id] = elem
        if isinstance(elem, PanelElement):
            for child in elem._children():
                self._index(child)

    @property
    def root(self) -> "Element | None":
        return self._root


# ───────────────────────── Surface selection ──────────────────────────────────


def build_surface() -> tuple["RendererFactory", "callable[[], None]"]:
    """Return (factory, flush) for the selected surface.

    For TextSurface: flush prints all collected lines to stdout.
    For RecordingSurface: flush is a no-op (lines are appended as they happen).
    """
    surface = os.environ.get("LUX_SURFACE", "text").lower()
    if surface == "text":
        out = TextOutput()
        factory = TextRendererFactory(out)

        def flush_text() -> None:
            lines = out.take()
            if not lines:
                return
            print("\n──── frame ────", flush=True)
            for line in lines:
                print(line, flush=True)

        return factory, flush_text
    if surface == "recording":
        path = os.environ.get("LUX_SPIKE_RECORDING_PATH", "/tmp/lux-spike-recording.jsonl")
        log = RecordingLog(path)
        factory = RecordingRendererFactory(log)
        print(f"[display] recording → {log.path}", flush=True)

        def flush_noop() -> None:
            pass

        return factory, flush_noop
    raise ValueError(f"unknown LUX_SURFACE: {surface!r} (expected text|recording)")


# ───────────────────────── Display main loop ──────────────────────────────────


def main() -> None:
    display_sock_path = os.environ.get("LUX_SPIKE_HUB_DISPLAY_SOCK", "/tmp/lux-spike-display.sock")
    frame_hz = float(os.environ.get("LUX_SPIKE_DISPLAY_HZ", "10"))
    stdin_disabled = os.environ.get("LUX_SPIKE_DISPLAY_NO_STDIN", "") == "1"

    print(f"[display] starting (hub_sock={display_sock_path}, hz={frame_hz})", flush=True)

    # Display-tier state.
    display = DisplayDisplay()
    renderer_factory, flush = build_surface()

    # Connect to Hub.
    hub_socket = connect_unix(display_sock_path)
    print("[display] connected to hub", flush=True)

    # Display-tier emit: Element behavior on Display side does not exist
    # in the spike — the Hub is the owner tier for behavior. emit is a
    # no-op here (Display Elements use the same Element ABC but their
    # injected emit never fires).
    def display_emit(event: object) -> None:
        pass

    element_factory = JsonElementFactory(renderer_factory=renderer_factory, emit=display_emit)

    # Handle inbound Updates from Hub.
    def handle_hub_message(payload: "WireDict") -> None:
        kind = payload.get("kind")
        if kind == "add_element":
            root_raw = payload["elem"]
            assert isinstance(root_raw, dict)
            root = element_factory.decode(root_raw)
            display.apply(AddElement(scene_id=str(payload["scene_id"]), parent_id=None, elem=root))
            print("[display] applied add_element", flush=True)
        elif kind == "set_property":
            display.apply(
                SetProperty(elem_id=str(payload["elem_id"]), field=str(payload["field"]), value=payload["value"])
            )
            print(f"[display] applied set_property({payload['elem_id']!r}, {payload['field']!r})", flush=True)
        else:
            print(f"[display] unknown hub message: {kind!r}", file=sys.stderr, flush=True)

    spawn_reader(hub_socket, handle_hub_message)

    # Simulated user input — read stdin for `click <elem_id>` lines.
    def stdin_loop() -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) == 2 and parts[0] == "click":
                elem_id = parts[1]
                msg = InteractionMessage(elem_id=elem_id, action="click")
                try:
                    hub_socket.send_line(encode_interaction(msg))
                    print(f"[display] sent click({elem_id})", flush=True)
                except OSError:
                    return
            else:
                print(f"[display] unknown stdin command: {line!r} (try: click <elem_id>)", file=sys.stderr, flush=True)

    if not stdin_disabled:
        threading.Thread(target=stdin_loop, name="display-stdin", daemon=True).start()

    # Render loop — runs forever at frame_hz. Walks scene; calls elem.render();
    # flushes the surface.
    frame_interval = 1.0 / frame_hz
    try:
        while True:
            root = display.root
            if root is not None:
                root.render()
                flush()
            time.sleep(frame_interval)
    except KeyboardInterrupt:
        print("[display] interrupted, exiting", flush=True)


if __name__ == "__main__":
    main()
