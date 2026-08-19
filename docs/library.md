# Python Library Guide

How a Python application drives the Lux Hub: the typed REST client, the
persistent listening client, and the direct MCP connection. This is
developer documentation; the [README](../README.md) covers users.

## `LuxRestClient` — the typed client of `luxd`

`LuxRestClient` is the public Python client of `luxd`. A downstream application
reaches the Hub through this typed client — not by hand-rolling REST calls — so it
gets the same validation, typing, and identity handling the CLI does. It imports
without the `[display]` extra (no ImGui/OpenGL pulled in).

```python
from punt_lux import LuxRestClient, RenderRequest, SceneShown

# connect() locates a running luxd and derives this invocation's identity from
# the git repository it runs in — so the scene below is owned by that repo.
client = LuxRestClient.connect()

result = client.render(
    RenderRequest(
        scene_id="hello",
        elements=[{"kind": "text", "id": "t1", "content": "Hello from Python"}],
    )
)
if isinstance(result, SceneShown):
    print("shown:", result.scene_id)
```

Every request carries the caller's `X-Lux-Client-*` identity headers, so each
installed scene is attributed to its repository rather than an anonymous caller.
Identity header values are percent-encoded on the wire (plain ASCII values
cross unchanged); the Hub decodes them, so a caller hand-rolling these headers
instead of using the clients must encode them the same way. An unreachable
`luxd` raises `HubUnavailableError`; a reachable Hub's refusal of a request
comes back as a typed `OpError` in the result.

## Listening: a persistent hub client

A daemon that wants to *receive* — pub-sub events it subscribed to, and the menu
callbacks the user clicked — holds one WebSocket to `luxd` with `LuxHubClient`.
It shares the identity of a `LuxRestClient`, so a callback the daemon registers
over REST is delivered on this stream. The receive loop renews the lease on every
contact and reconnects on a dropped connection, re-subscribing automatically; the
Hub buffers any clicks missed during a gap and drains them on reconnect.

Re-subscribing restores topics, but a menu callback lives on the session's lease,
which lapses during a long outage — so register it (and re-push scenes) in
`on_connect`, which runs after *every* handshake, first connect and each
reconnect. Registering in an outer register-then-listen sequence would run once;
the internal reconnect would never re-run it, and the menu entry would stay gone.

```python
import asyncio

from punt_lux import ClientIdentity, LuxRestClient

# One identity for both legs: scene pushes over REST, the listen stream over the
# WebSocket. A long-lived daemon declares an "app" identity — who it is, not where
# it ran — and a short lease TTL so its menu entries leave when it dies.
rest = LuxRestClient.for_identity(ClientIdentity(kind="app", name="voxd", lease_ttl=30))

def on_callback(callback_id: str) -> None:
    print("menu click:", callback_id)          # e.g. run the action for this item

def on_event(topic: str, payload: dict[str, object]) -> None:
    print("event:", topic, payload)            # e.g. {"album_id": "jazz-1"}

def on_connect() -> None:
    # Runs after every handshake — re-establish the per-connection state the
    # reconnect does not: register menu callbacks, re-push any scenes.
    rest.register_callback("music", "Music")

listener = rest.listener(
    on_callback=on_callback, on_event=on_event, on_connect=on_connect
)
listener.subscribe("music.play", "music.stop")
asyncio.run(listener.listen())                 # blocks, reconnecting as needed
```

Registering from `on_connect` is required, not merely tidy: the Hub refuses a
callback from a connection that holds no listen leg, and the handshake this hook
fires after is what gives this connection one. It is also what re-establishes the
entry after a reconnect, since a callback lives on the session's lease.

The handlers may be sync or async; the loop awaits a coroutine. A raising
`on_connect` is logged and the connection continues — a failed re-registration
never tears down a healthy socket. Call `stop()` to end the loop after its current
connection closes. Events and callbacks are generic — the topics and callback ids
are the app's own vocabulary, not Lux's.

The reference third-party app built on this pattern is vox's music player:
`voxd` registers a Music menu entry, receives clicks and transport events over
its listener, and pushes the player scene over REST.

## What a published event carries

An element publishes in one of two ways, and they carry different things.

**A `publish` list on a handler sends the interaction.** Declare it as the
button sugar `"publish": ["music.play"]`, or as a `wrap` entry on any element's
`handlers` list, and every interaction on that element publishes what the user
did:

```json
{"kind": "table", "id": "albums", "columns": ["Album"],
 "rows": [["dawn"], ["dusk"], ["noon"]], "selection_mode": "single",
 "handlers": [{"event": "row_selection_changed", "factory": "noop",
               "wrap": [{"decorator": "publish", "topics": ["music.play"]}]}]}
```

A click on the second row delivers:

```python
("music.play", {"kind": "row_selection_changed",
                "scene_id": "player", "element_id": "albums",
                "row_ids": ["dusk"], "anchor": "dusk"})
```

Every payload opens with the same three keys — what happened, and the scene and
element it happened on — so a subscriber never has to infer either. After those
come the event's own fields:

| `kind` | Fields it adds |
|---|---|
| `button_clicked` | *(none — the click is the whole event)* |
| `modal_closed` | *(none)* |
| `value_changed` | `value` — the input's committed value |
| `tab_changed` | `tab_id` — the newly-active tab |
| `header_toggled` | `open` — the header's new state |
| `row_selection_changed` | `row_ids` (the full selection) and `anchor` (the row the user just touched) |

`anchor` is the one to read when acting on a single row: the selection is a set
and cannot say which row the click landed on. The owning client's id is not in
the payload — publish fan-out is scoped to the publishing connection, so a
subscriber only ever receives its own scope's events.

**A button's `publish` mapping sends a message you wrote.** Where the interaction
is not what the subscriber cares about, give the button a topic and a payload of
your own:

```json
{"kind": "button", "id": "play-jazz-1", "label": "Play",
 "publish": {"topic": "music.play", "payload": {"album_id": "jazz-1"}}}
```

That delivers `("music.play", {"album_id": "jazz-1"})` — the payload verbatim,
with nothing added.

## Connecting to `luxd`'s MCP endpoint directly

This is how the plugin connects, and a session configured by hand connects the
same way: straight to `luxd`'s HTTP endpoint (`http://127.0.0.1:8430/mcp`), with
no per-session process in the path. A copy-paste example is in
[`plugin/.claude-plugin/mcp-http.example.json`](../plugin/.claude-plugin/mcp-http.example.json).

Such a session gets the whole tool surface but owns no menu entries, because it
holds no connection a click could arrive on. Menu entries belong to the session's
**applets** — `lux-beads` and the like — which the session-start hook launches
and which hold their own listener; `register_callback` from the tool surface is
refused, saying so.

Start `luxd` first (`lux hub-install` and start the service, or run `luxd` in a
terminal), then verify the direct connection end to end:

```bash
uv run python scripts/direct_connection_probe.py
```

The probe initializes a session, lists the tool surface, and calls a read-only
tool. `luxd` binds loopback only and refuses a non-loopback `--host` at startup;
remote access awaits authentication.
