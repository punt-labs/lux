"""Agent process — issues commands to the Hub and receives published Events.

Per io-model.md §"Agent observers" agents register their interest in
topics via `subscribe`; when the Hub publishes an Event on that topic,
each subscriber receives an `observed` notification and runs its local
handler.

Canonical AGNT verbs:
  - subscribe — register interest in a topic with the Hub
  - send      — bytes onto the Hub socket (e.g. `show` command)
  - receive   — bytes off the Hub socket (push notifications)
  - decode    — bytes → wire dict
  - notify    — the local handler runs for an observed Event
"""

from __future__ import annotations

import os
import sys
import time
from typing import TYPE_CHECKING

from lux_spike.connection import LineSocket, connect_unix, spawn_reader

if TYPE_CHECKING:
    from lux_spike.connection import WireDict


def main() -> None:
    agent_sock_path = os.environ.get("LUX_SPIKE_HUB_AGENT_SOCK", "/tmp/lux-spike-agent.sock")
    run_seconds = float(os.environ.get("LUX_SPIKE_AGENT_RUN_SECONDS", "30"))
    scene_id = os.environ.get("LUX_SPIKE_AGENT_SCENE_ID", "scene1")
    panel_id = os.environ.get("LUX_SPIKE_AGENT_PANEL_ID", "p1")
    label_id = os.environ.get("LUX_SPIKE_AGENT_LABEL_ID", "lbl1")
    button_id = os.environ.get("LUX_SPIKE_AGENT_BUTTON_ID", "btn1")

    print(f"[agent] starting (HUB sock={agent_sock_path})", flush=True)

    hub_socket = connect_unix(agent_sock_path)
    print("[agent] connected to HUB", flush=True)

    # Notification handler — the agent's local callback for observed Events.
    # When the Hub publishes a topic this agent is subscribed to, the Hub
    # sends an `observed` envelope and this handler runs (notify step).
    def handle(payload: "WireDict") -> None:
        if payload.get("kind") == "observed":
            topic = payload.get("topic")
            inner = payload.get("payload")
            print(f"[agent] notified — topic={topic!r} payload={inner!r}", flush=True)
        else:
            print(f"[agent] unknown HUB message: {payload!r}", file=sys.stderr, flush=True)

    spawn_reader(hub_socket, handle)

    # Subscribe to the two topics this agent observes.
    hub_socket.send_line({"kind": "subscribe", "topic": "scene.accepted"})
    print("[agent] subscribed to 'scene.accepted'", flush=True)
    hub_socket.send_line({"kind": "subscribe", "topic": f"interaction.{button_id}"})
    print(f"[agent] subscribed to 'interaction.{button_id}'", flush=True)

    # Send a `show` command — a Panel composite holding a Label and a Button.
    # The Hub will decode + instantiate Hub-tier Elements (rf=Null),
    # accept the resulting scene into hub_display, encode + send the
    # AddElement Update to DISP, and publish 'scene.accepted' to subscribers.
    root = {
        "kind": "panel",
        "id": panel_id,
        "children": [
            {"kind": "label",  "id": label_id,  "content": "ticks: 0"},
            {"kind": "button", "id": button_id, "label": "Click me"},
        ],
    }
    hub_socket.send_line({"kind": "show", "scene_id": scene_id, "root": root})
    print(f"[agent] sent show({scene_id!r}) to HUB", flush=True)

    # Run for run_seconds then exit (the spike's main demo loop).
    try:
        time.sleep(run_seconds)
    except KeyboardInterrupt:
        pass
    print("[agent] exiting", flush=True)


if __name__ == "__main__":
    main()
