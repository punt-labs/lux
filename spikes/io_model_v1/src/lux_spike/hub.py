"""Hub process — authoritative state owner.

Per io-model.md the Hub is the only tier that *accepts* state changes
(the moment that hub_display becomes authoritative for new content);
every other tier *applies* the resulting Update to mirror it. The Hub
also resolves Elements for inbound Interactions, invokes their behavior
methods, and publishes the emitted Events to topic subscribers.

Canonical Hub verbs:
  - receive  — bytes off an inbound socket
  - decode   — bytes → wire dict + instantiate per-kind Element (rf=Null)
  - accept   — commit a state change to hub_display (Hub is authoritative)
  - encode   — Update → wire dict → bytes
  - send     — bytes onto the Display socket
  - resolve  — look up an Element on hub_display by id
  - invoke   — call a behavior method on a resolved Element
  - publish  — fan out an emitted Event to topic subscribers

The Hub gets NullRendererFactory. The Hub has no render loop. IPC
carries Updates and Events — not render calls.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
from typing import TYPE_CHECKING

from lux_spike.codec import (
    JsonElementFactory,
    JsonEncoderFactory,
    UpdateCodec,
    decode_interaction,
    encode_button_clicked,
)
from lux_spike.connection import LineSocket, listen_unix, spawn_reader
from lux_spike.elements import ButtonElement, LabelElement, PanelElement
from lux_spike.renderers.null import NullRendererFactory
from lux_spike.updates import AddElement, ButtonClicked, SetProperty

if TYPE_CHECKING:
    from lux_spike.connection import WireDict
    from lux_spike.element import Element


class HubDisplay:
    """Authoritative tier-local state.

    The verb here is `accept` (not `apply`) because Hub is the source of
    truth — once `accept` returns, hub_display reflects the new committed
    state. Other tiers (DISP) `apply` the same Update to mirror it; the
    state-mutation primitive is identical, but the role differs: Hub commits,
    DISP mirrors. Naming the method `accept` keeps that boundary explicit."""

    _by_id: dict[str, "Element"]
    _root_id: str | None

    def __new__(cls) -> "HubDisplay":
        self = object.__new__(cls)
        self._by_id = {}
        self._root_id = None
        return self

    def accept(self, update: AddElement | SetProperty) -> None:
        match update:
            case AddElement(elem=elem, parent_id=parent_id):
                self._index(elem)
                if parent_id is None:
                    self._root_id = _get_id(elem)
                # Composites already carry their children in the decoded tree;
                # add_element with a parent appends (not used in PR-3 spike).
            case SetProperty(elem_id=eid, field=field, value=value):
                elem = self._by_id.get(eid)
                if elem is None:
                    return
                # Spike-scope: only `content` on LabelElement is mutated.
                if isinstance(elem, LabelElement) and field == "content":
                    elem._set_content(str(value))

    def _index(self, elem: "Element") -> None:
        self._by_id[_get_id(elem)] = elem
        if isinstance(elem, PanelElement):
            for child in elem._children():
                self._index(child)

    def resolve(self, elem_id: str) -> "Element | None":
        """Find an Element on hub_display by id. Used to route an inbound
        InteractionMessage to the right Element's behavior method."""
        return self._by_id.get(elem_id)

    def root(self) -> "Element | None":
        if self._root_id is None:
            return None
        return self._by_id.get(self._root_id)

    def all_label_ids(self) -> list[str]:
        return [eid for eid, elem in self._by_id.items() if isinstance(elem, LabelElement)]


def _get_id(elem: "Element") -> str:
    if isinstance(elem, LabelElement | ButtonElement | PanelElement):
        return elem.id
    raise TypeError(f"no id accessor for {type(elem).__name__}")


class SubscriptionRegistry:
    """Hub-side topic→sockets registry per io-model.md §"Agent observers".
    Thread-safe."""

    _by_topic: dict[str, set[LineSocket]]
    _lock: threading.Lock

    def __new__(cls) -> "SubscriptionRegistry":
        self = object.__new__(cls)
        self._by_topic = {}
        self._lock = threading.Lock()
        return self

    def subscribe(self, topic: str, sock: LineSocket) -> None:
        with self._lock:
            self._by_topic.setdefault(topic, set()).add(sock)

    def remove_socket(self, sock: LineSocket) -> None:
        with self._lock:
            for subs in self._by_topic.values():
                subs.discard(sock)

    def publish(self, topic: str, payload: "WireDict") -> int:
        """Fan out `observed` notification to every subscriber.
        Returns the number of subscriber sockets the notification was sent to."""
        with self._lock:
            subs = list(self._by_topic.get(topic, ()))
        delivered = 0
        for s in subs:
            try:
                s.send_line({"kind": "observed", "topic": topic, "payload": payload})
                delivered += 1
            except OSError:
                pass
        return delivered


# ────────────────────────── Hub main loop ─────────────────────────────────────


def main() -> None:
    agent_sock_path = os.environ.get("LUX_SPIKE_HUB_AGENT_SOCK", "/tmp/lux-spike-agent.sock")
    display_sock_path = os.environ.get("LUX_SPIKE_HUB_DISPLAY_SOCK", "/tmp/lux-spike-display.sock")
    tick_seconds = float(os.environ.get("LUX_SPIKE_HUB_TICK_SECONDS", "2.0"))

    print(f"[hub] starting (AGNT sock={agent_sock_path}, DISP sock={display_sock_path})", flush=True)

    # Hub-tier state.
    display = HubDisplay()
    registry = SubscriptionRegistry()
    null_rf = NullRendererFactory()

    # The Hub's emit callback receives Events EMITTED by Element behavior
    # methods. The Hub responds by PUBLISHING the Event to topic subscribers.
    def hub_emit(event: object) -> None:
        match event:
            case ButtonClicked():
                topic = f"interaction.{event.elem_id}"
                payload = encode_button_clicked(event)
                n = registry.publish(topic, payload)
                print(f"[hub] published {topic!r} payload={payload} → {n} subscriber(s)", flush=True)
            case _:
                # Other Event types — no-op in spike scope.
                pass

    element_factory = JsonElementFactory(renderer_factory=null_rf, emit=hub_emit)
    encoder_factory = JsonEncoderFactory()
    update_codec = UpdateCodec(encoder=encoder_factory, decoder=element_factory)

    # Display connection — wait for Display to connect.
    display_sock_holder: dict[str, LineSocket] = {}
    display_sock_lock = threading.Lock()

    def with_display(fn) -> bool:
        with display_sock_lock:
            sock = display_sock_holder.get("sock")
            if sock is None:
                return False
            try:
                fn(sock)
                return True
            except OSError:
                return False

    def handle_display_message(payload: "WireDict") -> None:
        kind = payload.get("kind")
        if kind == "interaction":
            msg = decode_interaction(payload)
            print(f"[hub] received InteractionMessage from DISP: elem_id={msg.elem_id!r} action={msg.action!r}", flush=True)
            elem = display.resolve(msg.elem_id)
            if elem is None:
                print(f"[hub] WARN: could not resolve elem_id={msg.elem_id!r} on hub_display; dropping", file=sys.stderr, flush=True)
                return
            print(f"[hub] resolved {type(elem).__name__}[{msg.elem_id}] on hub_display", flush=True)
            if isinstance(elem, ButtonElement) and msg.action == "click":
                print(f"[hub] invoked {type(elem).__name__}.on_click()", flush=True)
                elem.on_click()  # emits ButtonClicked → hub_emit → published as 'interaction.<id>'
        else:
            print(f"[hub] unknown DISP message: {kind!r}", file=sys.stderr, flush=True)

    def handle_agent_message(agent_sock: LineSocket, payload: "WireDict") -> None:
        kind = payload.get("kind")
        if kind == "subscribe":
            topic = str(payload["topic"])
            registry.subscribe(topic, agent_sock)
            print(f"[hub] AGNT subscribed to {topic!r}", flush=True)
        elif kind == "synthesize_interaction":
            # Test-only path: equivalent to receiving an InteractionMessage from
            # the Display, but injected via the agent socket so a test can drive
            # R3 without poking the Display process's stdin. Runs the same
            # Hub-side code path that handle_display_message does for "interaction".
            elem_id = str(payload["elem_id"])
            action = str(payload["action"])
            elem = display.resolve(elem_id)
            if isinstance(elem, ButtonElement) and action == "click":
                elem.on_click()
        elif kind == "show":
            scene_id = str(payload["scene_id"])
            root_raw = payload["root"]
            assert isinstance(root_raw, dict)
            # 1. decode: parse wire dict, instantiate Hub-tier Element tree (rf=Null)
            root = element_factory.decode(root_raw)
            update = AddElement(scene_id=scene_id, parent_id=None, elem=root)
            # 2. accept: commit to hub_display (Hub is now authoritative for this scene)
            display.accept(update)
            print(f"[hub] accepted scene {scene_id!r} (hub_display is authoritative)", flush=True)
            # 3. encode + send: ship the AddElement Update to DISP
            wire = update_codec.encode(update)
            sent = with_display(lambda s: s.send_line(wire))
            if not sent:
                print("[hub] WARN: no DISP connected; AddElement Update was not sent", file=sys.stderr, flush=True)
            else:
                print(f"[hub] sent AddElement Update to DISP (scene_id={scene_id!r})", flush=True)
            # 4. publish: notify subscribers that Hub has accepted the scene
            n = registry.publish("scene.accepted", {"scene_id": scene_id})
            print(f"[hub] published 'scene.accepted' → {n} subscriber(s)", flush=True)
        else:
            print(f"[hub] unknown AGNT message: {kind!r}", file=sys.stderr, flush=True)

    # Background timer thread: mutates the first Label every tick_seconds.
    stop_event = threading.Event()

    def timer_loop() -> None:
        tick = 0
        while not stop_event.is_set():
            stop_event.wait(tick_seconds)
            if stop_event.is_set():
                return
            tick += 1
            label_ids = display.all_label_ids()
            if not label_ids:
                continue
            label_id = label_ids[0]
            new_content = f"ticks: {tick}"
            update = SetProperty(elem_id=label_id, field="content", value=new_content)
            # Hub timer is itself a source of authoritative state changes —
            # 1. accept the Update on hub_display, then 2. encode + send to DISP.
            display.accept(update)
            print(f"[hub] timer tick {tick} → accepted SetProperty({label_id}, content={new_content!r})", flush=True)
            wire = update_codec.encode(update)
            with_display(lambda s: s.send_line(wire))

    threading.Thread(target=timer_loop, name="hub-timer", daemon=True).start()

    # Bind both Unix sockets and accept connections.
    with listen_unix(display_sock_path) as display_listen, listen_unix(agent_sock_path) as agent_listen:
        # Display connects first; one display per spike run.
        display_listen.settimeout(30.0)
        try:
            display_sock_raw, _ = display_listen.accept()
        except socket.timeout:
            print("[hub] timed out waiting for DISP to connect", file=sys.stderr, flush=True)
            return
        display_line = LineSocket(display_sock_raw)
        with display_sock_lock:
            display_sock_holder["sock"] = display_line
        spawn_reader(display_line, handle_display_message)
        print("[hub] DISP connected", flush=True)

        # Now accept agents one at a time (spike-scope: one agent).
        agent_listen.settimeout(None)
        while not stop_event.is_set():
            try:
                agent_sock_raw, _ = agent_listen.accept()
            except OSError:
                break
            agent_line = LineSocket(agent_sock_raw)
            print("[hub] AGNT connected", flush=True)
            spawn_reader(agent_line, lambda payload, s=agent_line: handle_agent_message(s, payload))


if __name__ == "__main__":
    main()
