"""Agent process — connects to Hub, subscribes to topics, sends a show()
command, prints received push notifications.

Per io-model.md §"Agent observers": agents subscribe to topics; Hub
publishes; subscribers receive push notifications.
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

    print(f"[agent] starting (hub_sock={agent_sock_path})", flush=True)

    hub_socket = connect_unix(agent_sock_path)
    print("[agent] connected to hub", flush=True)

    # Notification handler — prints push messages.
    def handle(payload: "WireDict") -> None:
        if payload.get("kind") == "observed":
            topic = payload.get("topic")
            inner = payload.get("payload")
            print(f"[agent] observed {topic!r} → {inner!r}", flush=True)
        else:
            print(f"[agent] unknown message: {payload!r}", file=sys.stderr, flush=True)

    spawn_reader(hub_socket, handle)

    # Subscribe to the two topics we care about.
    hub_socket.send_line({"kind": "subscribe", "topic": "scene.applied"})
    hub_socket.send_line({"kind": "subscribe", "topic": f"interaction.{button_id}"})

    # Send a show command — a Panel composite holding a Label and a Button.
    root = {
        "kind": "panel",
        "id": panel_id,
        "children": [
            {"kind": "label",  "id": label_id,  "content": "ticks: 0"},
            {"kind": "button", "id": button_id, "label": "Click me"},
        ],
    }
    hub_socket.send_line({"kind": "show", "scene_id": scene_id, "root": root})
    print(f"[agent] sent show({scene_id!r})", flush=True)

    # Run for run_seconds then exit (the spike's main demo loop).
    try:
        time.sleep(run_seconds)
    except KeyboardInterrupt:
        pass
    print("[agent] exiting", flush=True)


if __name__ == "__main__":
    main()
