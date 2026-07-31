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
An unreachable `luxd` raises `HubUnavailableError`; a reachable Hub's refusal of a
request comes back as a typed `OpError` in the result.

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

## Connecting to `luxd`'s MCP endpoint directly

A session that connects straight to `luxd`'s HTTP endpoint
(`http://127.0.0.1:8430/mcp`) needs no bridge — a copy-paste example is in
[`.claude-plugin/mcp-http.example.json`](../.claude-plugin/mcp-http.example.json).
Such a session gets the whole tool surface but no menu entries of its own, since
it holds no connection a click could arrive on (see the README's
[architecture section](../README.md#architecture) for why menu entries require
the per-session `lux mcp-serve` process).

Start `luxd` first (`lux hub-install` and start the service, or run `luxd` in a
terminal), then verify the direct connection end to end:

```bash
uv run python scripts/direct_connection_probe.py
```

The probe initializes a session, lists the tool surface, and calls a read-only
tool. `luxd` binds loopback only and refuses a non-loopback `--host` at startup;
remote access awaits authentication.
