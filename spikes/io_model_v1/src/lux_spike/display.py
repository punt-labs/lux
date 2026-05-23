"""Display process — local mirror of Hub state + render loop + user-input detector.

Per io-model.md the Display is the only tier with a render loop. It
decodes inbound Updates from the Hub, applies them to its local mirror
(display_display), and on each frame walks the local Element tree
calling elem.render() through its surface-bound RendererFactory
(TextRendererFactory or RecordingRendererFactory).

The Display is also the only tier where user input enters the system.
Its stdin reader thread detects keystrokes, encodes them as
InteractionMessages, and sends them to the Hub for resolution and
behavior invocation.

Canonical DISP verbs:
  - receive  — bytes off the Hub socket
  - decode   — bytes → wire dict + instantiate per-kind Element (rf=Surface)
  - apply    — mirror an Update into display_display (Hub remains authoritative)
  - render   — walk display_display, call elem.render() per-frame, paint surface
  - detect   — recognize a user input event (stdin keystroke in this spike)
  - encode   — InteractionMessage → wire dict → bytes
  - send     — bytes onto the Hub socket
"""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import TYPE_CHECKING

from lux_spike.codec import JsonElementFactory, encode_interaction
from lux_spike.connection import LineSocket, connect_unix, spawn_reader
from lux_spike.elements import ButtonElement, DialogElement, LabelElement, PanelElement
from lux_spike.renderers.recording import RecordingLog, RecordingRendererFactory
from lux_spike.renderers.text import TextOutput, TextRendererFactory
from lux_spike.updates import AddElement, InteractionMessage, RemoveElement, SetProperty

if TYPE_CHECKING:
    from lux_spike.connection import WireDict
    from lux_spike.element import Element
    from lux_spike.protocols import RendererFactory


class DisplayDisplay:
    """Display-tier local mirror of Hub state.

    The verb here is `apply` (not `accept`) because Hub is the source of
    truth — DISP is mirroring committed state. Once Hub accepts an Update,
    it ships it; DISP applies it to display_display so the next render
    frame reflects the new state. The render loop walks this tree every
    tick to paint the surface."""

    _by_id: dict[str, "Element"]
    _root: "Element | None"

    def __new__(cls) -> "DisplayDisplay":
        self = object.__new__(cls)
        self._by_id = {}
        self._root = None
        return self

    def apply(self, update: AddElement | SetProperty | RemoveElement) -> None:
        match update:
            case AddElement(elem=elem, parent_id=parent_id):
                if parent_id is None:
                    # Whole-scene replacement: drop old indices before
                    # installing the new tree (mirrors HubDisplay.accept).
                    self._by_id.clear()
                    self._root = None
                    self._index(elem)
                    self._root = elem
                else:
                    self._index(elem)
            case SetProperty(elem_id=eid, field=field, value=value):
                elem = self._by_id.get(eid)
                if elem is None:
                    return
                if isinstance(elem, LabelElement) and field == "content":
                    elem._set_content(str(value))
            case RemoveElement(elem_id=eid):
                self._remove_subtree(eid)
                if self._root is not None and isinstance(
                    self._root, LabelElement | ButtonElement | PanelElement | DialogElement
                ) and self._root.id == eid:
                    self._root = None

    def _index(self, elem: "Element") -> None:
        if isinstance(elem, LabelElement | ButtonElement | PanelElement | DialogElement):
            self._by_id[elem.id] = elem
        if isinstance(elem, PanelElement | DialogElement):
            for child in elem._children():
                self._index(child)

    def _remove_subtree(self, elem_id: str) -> None:
        elem = self._by_id.pop(elem_id, None)
        if elem is None:
            return
        if isinstance(elem, PanelElement | DialogElement):
            for child in elem._children():
                if isinstance(child, LabelElement | ButtonElement | PanelElement | DialogElement):
                    self._remove_subtree(child.id)

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

    print(f"[display] starting (HUB sock={display_sock_path}, hz={frame_hz})", flush=True)

    # Display-tier local mirror + surface.
    display = DisplayDisplay()
    renderer_factory, flush = build_surface()

    # Connect to Hub.
    hub_socket = connect_unix(display_sock_path)
    print("[display] connected to HUB", flush=True)

    # Display-tier emit: Element behavior on the Display side does not run
    # in this spike — the Hub is the owner tier for behavior (it RESOLVES
    # the Element by id on hub_display and INVOKES on_click there). DISP
    # Elements use the same Element ABC but their injected emit is a no-op.
    def display_emit(event: object) -> None:
        pass

    element_factory = JsonElementFactory(renderer_factory=renderer_factory, emit=display_emit)

    # Handle inbound Updates from Hub.
    # Per io-model.md: IPC carries Updates and Events — never render calls.
    # DISP receives an Update, decodes it (instantiating DISP-tier Elements
    # with rf=surface), and applies it to display_display. The render loop
    # picks up the new state on the next frame.
    def handle_hub_message(payload: "WireDict") -> None:
        kind = payload.get("kind")
        if kind == "add_element":
            root_raw = payload["elem"]
            assert isinstance(root_raw, dict)
            # decode + instantiate: build DISP-tier Element tree (rf=Surface)
            root = element_factory.decode(root_raw)
            # apply: mirror into display_display (Hub remains authoritative)
            display.apply(AddElement(
                scene_id=str(payload["scene_id"]),
                parent_id=None,
                elem=root,
            ))
            print("[display] decoded + instantiated DISP-tier Element tree; applied AddElement to display_display", flush=True)
        elif kind == "set_property":
            display.apply(
                SetProperty(elem_id=str(payload["elem_id"]), field=str(payload["field"]), value=payload["value"])
            )
            print(f"[display] applied SetProperty({payload['elem_id']!r}, {payload['field']!r}) to display_display", flush=True)
        elif kind == "remove_element":
            elem_id = str(payload["elem_id"])
            display.apply(RemoveElement(elem_id=elem_id))
            print(f"[display] applied RemoveElement({elem_id!r}) to display_display", flush=True)
        else:
            print(f"[display] unknown HUB message: {kind!r}", file=sys.stderr, flush=True)

    spawn_reader(hub_socket, handle_hub_message)

    # User-input detector — read stdin for `click <elem_id>` lines.
    # DISP is the only tier where user input ENTERS the system. The
    # detector encodes the keystroke as an InteractionMessage and sends
    # it to the Hub for RESOLVE → INVOKE → EMIT → PUBLISH.
    def stdin_loop() -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) == 2 and parts[0] == "click":
                elem_id = parts[1]
                print(f"[display] detected click({elem_id}) from user", flush=True)
                msg = InteractionMessage(elem_id=elem_id, action="click")
                try:
                    hub_socket.send_line(encode_interaction(msg))
                    print(f"[display] encoded + sent InteractionMessage to HUB", flush=True)
                except OSError:
                    return
            else:
                print(f"[display] unknown stdin command: {line!r} (try: click <elem_id>)", file=sys.stderr, flush=True)

    if not stdin_disabled:
        threading.Thread(target=stdin_loop, name="display-stdin", daemon=True).start()

    # Render loop — runs forever at frame_hz. Walks display_display each
    # frame and calls elem.render(); the surface paints the result.
    # Per io-model.md the render loop is independent of IPC activity —
    # it draws whatever state display_display currently holds.
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
