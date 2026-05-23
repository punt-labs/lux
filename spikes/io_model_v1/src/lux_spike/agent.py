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

Two modes (selected via env var LUX_SPIKE_AGENT_MODE):

  - "basic"  (default) — sends one show() of Panel{Label, Button}, then waits.
                          Used by R1, R2, R3.
  - "dialog"           — sends a Yes/No dialog; when the user clicks Yes,
                          AGNT performs a short computation and sends a NEW
                          show() that REPLACES the dialog with a result scene.
                          Used by R4.
"""

from __future__ import annotations

import os
import sys
import time
from typing import TYPE_CHECKING

from lux_spike.connection import connect_unix, spawn_reader

if TYPE_CHECKING:
    from lux_spike.connection import LineSocket, WireDict


# ─────────────────────────── basic mode (R1/R2/R3) ────────────────────────────


def _basic_mode(hub_socket: "LineSocket", run_seconds: float) -> None:
    """One-shot Panel{Label, Button} scene. No reactive behavior."""
    scene_id = os.environ.get("LUX_SPIKE_AGENT_SCENE_ID", "scene1")
    panel_id = os.environ.get("LUX_SPIKE_AGENT_PANEL_ID", "p1")
    label_id = os.environ.get("LUX_SPIKE_AGENT_LABEL_ID", "lbl1")
    button_id = os.environ.get("LUX_SPIKE_AGENT_BUTTON_ID", "btn1")

    def handle(payload: "WireDict") -> None:
        if payload.get("kind") == "observed":
            topic = payload.get("topic")
            inner = payload.get("payload")
            print(f"[agent] notified — topic={topic!r} payload={inner!r}", flush=True)
        else:
            print(f"[agent] unknown HUB message: {payload!r}", file=sys.stderr, flush=True)

    spawn_reader(hub_socket, handle)

    hub_socket.send_line({"kind": "subscribe", "topic": "scene.accepted"})
    print("[agent] subscribed to 'scene.accepted'", flush=True)
    hub_socket.send_line({"kind": "subscribe", "topic": f"interaction.{button_id}"})
    print(f"[agent] subscribed to 'interaction.{button_id}'", flush=True)

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

    _idle_until(run_seconds)


# ─────────────────────────── dialog mode (R4) ─────────────────────────────────


_DIALOG_SCENE_ID = "dialog"
_RESULT_SCENE_ID = "result"
_CANCEL_SCENE_ID = "cancelled"


def _dialog_scene() -> dict[str, object]:
    """A Yes / No confirmation dialog. The wire kind is "dialog" (not
    "panel") so the HUB instantiates a DialogElement — which means its
    child buttons get bound to `dialog.close` at construction time, and
    clicking either button triggers the dialog's self-dismiss behavior
    through its own API."""
    return {
        "kind": "dialog",
        "id": "dlg",
        "children": [
            {"kind": "label",  "id": "dlg_q",     "content": "Save your work?"},
            {"kind": "button", "id": "btn_yes",   "label": "Yes"},
            {"kind": "button", "id": "btn_no",    "label": "No"},
        ],
    }


def _result_scene(*, result_text: str) -> dict[str, object]:
    """The agent's reply after the user clicks Yes — a Panel showing what
    happened. This entirely REPLACES the dialog scene (root parent_id=None
    triggers Hub's whole-scene-replace path)."""
    return {
        "kind": "panel",
        "id": "result_panel",
        "children": [
            {"kind": "label", "id": "result_status", "content": "Saved."},
            {"kind": "label", "id": "result_body",   "content": result_text},
        ],
    }


def _cancel_scene() -> dict[str, object]:
    return {
        "kind": "panel",
        "id": "cancel_panel",
        "children": [
            {"kind": "label", "id": "cancel_msg", "content": "Cancelled. Nothing was saved."},
        ],
    }


def _dialog_mode(hub_socket: "LineSocket", run_seconds: float) -> None:
    """Send a Yes/No dialog. The dialog is a DialogElement (kind="dialog"
    on the wire); the HUB's decoder wires its child buttons' on_click
    callbacks to `dialog.close()` at construction. When the user clicks
    a button, the HUB invokes the button's on_click, which calls the
    bound callback, which calls dialog.close(), which emits a
    RemoveElement Update. The HUB's emit handler accepts the Update on
    hub_display and ships it to DISP. The Dialog removes itself from
    its parent (the scene root) through its own API. No Hub-side flag,
    no special interaction-handler logic — pure OO behavior dispatch.

    AGNT subscribes to the buttons' interaction topics purely as an
    OBSERVER. On btn_yes, AGNT performs its work and independently
    composes a result scene to send to the HUB. AGNT never tells the
    HUB to dismiss anything; the dialog dismissed itself."""

    def handle(payload: "WireDict") -> None:
        if payload.get("kind") != "observed":
            print(f"[agent] unknown HUB message: {payload!r}", file=sys.stderr, flush=True)
            return
        topic = str(payload.get("topic"))
        inner = payload.get("payload")
        print(f"[agent] notified — topic={topic!r} payload={inner!r}", flush=True)

        if topic == "interaction.btn_yes":
            # AGNT is an observer of the click. By the time this
            # notification arrives the DialogElement on the HUB has
            # already called its own close() method (because the
            # button's on_click invoked it), so the dialog is gone
            # from hub_display and the RemoveElement Update is in
            # flight (or already applied) on DISP. AGNT's role is
            # purely to decide what scene comes next.
            print("[agent] observed btn_yes — performing computation for follow-up scene...", flush=True)
            time.sleep(0.3)  # simulated work — fetch / save / etc.
            result_text = f"Result: 42 (computed at t={time.strftime('%H:%M:%S')})"
            print("[agent] composing new scene (the dialog already dismissed itself on the HUB)", flush=True)
            hub_socket.send_line(
                {"kind": "show", "scene_id": _RESULT_SCENE_ID, "root": _result_scene(result_text=result_text)}
            )
            print(f"[agent] sent show({_RESULT_SCENE_ID!r}) to HUB", flush=True)
        elif topic == "interaction.btn_no":
            print("[agent] observed btn_no — composing cancellation scene", flush=True)
            hub_socket.send_line(
                {"kind": "show", "scene_id": _CANCEL_SCENE_ID, "root": _cancel_scene()}
            )
            print(f"[agent] sent show({_CANCEL_SCENE_ID!r}) to HUB", flush=True)

    spawn_reader(hub_socket, handle)

    # Subscribe to button events for both choices and to scene.accepted so we
    # see Hub's confirmation of every show() we send.
    hub_socket.send_line({"kind": "subscribe", "topic": "scene.accepted"})
    print("[agent] subscribed to 'scene.accepted'", flush=True)
    hub_socket.send_line({"kind": "subscribe", "topic": "interaction.btn_yes"})
    print("[agent] subscribed to 'interaction.btn_yes'", flush=True)
    hub_socket.send_line({"kind": "subscribe", "topic": "interaction.btn_no"})
    print("[agent] subscribed to 'interaction.btn_no'", flush=True)

    # Initial scene — the Yes/No dialog. The dialog knows how to close
    # itself (DialogElement.close); the HUB's decoder wires that to each
    # button's on_click callback. No special show()-level flags.
    hub_socket.send_line({
        "kind": "show",
        "scene_id": _DIALOG_SCENE_ID,
        "root": _dialog_scene(),
    })
    print(f"[agent] sent show({_DIALOG_SCENE_ID!r}) to HUB", flush=True)

    _idle_until(run_seconds)


# ─────────────────────────── entry point ──────────────────────────────────────


def _idle_until(run_seconds: float) -> None:
    try:
        time.sleep(run_seconds)
    except KeyboardInterrupt:
        pass
    print("[agent] exiting", flush=True)


def main() -> None:
    agent_sock_path = os.environ.get("LUX_SPIKE_HUB_AGENT_SOCK", "/tmp/lux-spike-agent.sock")
    run_seconds = float(os.environ.get("LUX_SPIKE_AGENT_RUN_SECONDS", "30"))
    mode = os.environ.get("LUX_SPIKE_AGENT_MODE", "basic").lower()

    print(f"[agent] starting (mode={mode!r}, HUB sock={agent_sock_path})", flush=True)

    hub_socket = connect_unix(agent_sock_path)
    print("[agent] connected to HUB", flush=True)

    if mode == "basic":
        _basic_mode(hub_socket, run_seconds)
    elif mode == "dialog":
        _dialog_mode(hub_socket, run_seconds)
    else:
        raise ValueError(f"unknown LUX_SPIKE_AGENT_MODE: {mode!r} (expected basic|dialog)")


if __name__ == "__main__":
    main()
