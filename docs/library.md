# Python Library Guide

How a Python application drives the Lux Hub: the `LuxClient` facade with its
noun-grouped accessors, the persistent listening client, and the direct MCP
connection. This is developer documentation; the [README](../README.md) covers
users.

## `LuxClient` — the public facade

`LuxClient` is the public Python library API of `luxd`. A downstream
application reaches the Hub through this typed facade — not by hand-rolling
REST calls, and not by holding the transport classes directly — so it gets the
same validation, typing, and identity handling every other surface does. It
imports without the `[display]` extra (no ImGui/OpenGL pulled in).

Every operation lives under a **noun-grouped accessor** — `client.scene.*`,
`client.frame.*`, `client.menu.*`, `client.session.*`, `client.callback.*`,
`client.display.*`, `client.event.*`, `client.error.*` — matching the
vocabulary the CLI, MCP, and REST surfaces speak. IDE completion on
`client.scene.` shows the noun's verbs; the same shape appears on
`lux scene <verb>` (CLI), `scene_<verb>` (MCP), and `/scenes` (REST).

```python
import asyncio

from punt_lux import LuxClient, RenderRequest, SceneShown, TextElement

# connect() locates a running luxd and derives this invocation's identity from
# the git repository it runs in — so the scene below is owned by that repo.
client = LuxClient.connect()


async def render_hello() -> None:
    result = await client.scene.show(
        RenderRequest(
            scene_id="hello",
            elements=[TextElement(id="t1", content="Hello from Python")],
        )
    )
    if isinstance(result, SceneShown):
        print("shown:", result.scene_id)


asyncio.run(render_hello())
```

Every request carries the caller's `X-Lux-Client-*` identity headers, so each
installed scene is attributed to its repository rather than an anonymous caller.
An unreachable `luxd` raises `HubUnavailableError`; a reachable Hub's refusal
of a request comes back as a typed `OpError` in the result.

Every accessor method is `async` and returns the typed operation result. The
facade dispatches through the shared command singletons in
`punt_lux.commands`, so a library caller executes the same code path as the
CLI, MCP, and REST adapters.

### Shipped accessors

The library facade exposes nine accessors this cycle:

| Accessor | Verbs |
|----------|-------|
| `client.scene` | `show`, `update`, `clear`, `clear_all`, `inspect`, `ls`, `table`, `dashboard` |
| `client.frame` | `close` |
| `client.menu` | `ls`, `set` |
| `client.session` | `ls`, `identify` |
| `client.callback` | `register` |
| `client.display` | `info`, `get_theme`, `get_window`, `get_mode`, `screenshot` |
| `client.event` | `ls` |
| `client.error` | `ls` |

Top-level (no noun grouping):

- `client.ping(wait=None)` — round-trip diagnostics
- `client.listener(...)` — build a persistent WebSocket listen client (see below)

Verbs deferred to follow-on beads: `client.frame.lower` / `client.frame.expire`
(`lux-01iw` / `lux-0qrw`, waiting on the MCP tools), `client.menu.get`
(`lux-m69c`), `client.session.inspect` (`lux-aom6`), `client.callback.pending`
(architecturally REST-unreachable — landing with the listen-leg wiring). The
`client.display.*` split verbs fuse into `client.display.theme(name=None)`
etc. once `lux-5pwu` lands. `client.topic.*` (publish / subscribe / receive)
lands once the REST routes ship or a listener-based accessor is chosen.

## Listening: a persistent hub client

A daemon that wants to *receive* — pub-sub events it subscribed to, and the
menu callbacks the user clicked — holds one WebSocket to `luxd` through
`client.listener(...)`. It shares the identity of the `LuxClient` that
built it, so a callback the daemon registered through `client.callback.register`
is delivered on this stream. The receive loop renews the lease on every
contact and reconnects on a dropped connection, re-subscribing automatically;
the Hub buffers any clicks missed during a gap and drains them on reconnect.

Re-subscribing restores topics, but a menu callback lives on the session's
lease, which lapses during a long outage — so register it (and re-push scenes)
in `on_connect`, which runs after *every* handshake, first connect and each
reconnect. Registering in an outer register-then-listen sequence would run
once; the internal reconnect would never re-run it, and the menu entry would
stay gone.

```python
import asyncio

from punt_lux import ClientIdentity, LuxClient

# One identity for both legs: scene pushes over REST, the listen stream over
# the WebSocket. A long-lived daemon declares an "app" identity — who it is,
# not where it ran — and a short lease TTL so its menu entries leave when it
# dies.
client = LuxClient.for_identity(ClientIdentity(kind="app", name="voxd", lease_ttl=30))


async def on_callback(callback_id: str) -> None:
    print("menu click:", callback_id)  # run the action for this item


async def on_event(topic: str, payload: dict[str, object]) -> None:
    print("event:", topic, payload)  # e.g. {"album_id": "jazz-1"}


async def on_connect() -> None:
    # Runs after every handshake — re-establish the per-connection state the
    # reconnect does not: register menu callbacks, re-push any scenes.
    await client.callback.register("music", "Music")


listener = client.listener(
    on_callback=on_callback, on_event=on_event, on_connect=on_connect
)
listener.subscribe("music.play", "music.stop")
asyncio.run(listener.listen())  # blocks, reconnecting as needed
```

Registering from `on_connect` is required, not merely tidy: the Hub refuses a
callback from a connection that holds no listen leg, and the handshake this
hook fires after is what gives this connection one. It is also what
re-establishes the entry after a reconnect, since a callback lives on the
session's lease.

The handlers may be sync or async; the loop awaits a coroutine. A raising
`on_connect` is logged and the connection continues — a failed re-registration
never tears down a healthy socket. Call `listener.stop()` to end the loop after
its current connection closes. Events and callbacks are generic — the topics
and callback ids are the app's own vocabulary, not Lux's.

The reference third-party app built on this pattern is vox's music player:
`voxd` registers a Music menu entry, receives clicks and transport events over
its listener, and pushes the player scene through `client.scene.show`.

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
(
    "music.play",
    {
        "kind": "row_selection_changed",
        "scene_id": "player",
        "element_id": "albums",
        "row_ids": ["dusk"],
        "anchor": "dusk",
    },
)
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

**A button's `publish` mapping sends a message you wrote.** Where the
interaction is not what the subscriber cares about, give the button a topic and
a payload of your own:

```json
{"kind": "button", "id": "play-jazz-1", "label": "Play",
 "publish": {"topic": "music.play", "payload": {"album_id": "jazz-1"}}}
```

That delivers `("music.play", {"album_id": "jazz-1"})` — the payload verbatim,
with nothing added.

## Migrating from the old transport-flavoured names

The REST transport is now a private implementation detail of `LuxClient`
(`punt_lux.client._rest_transport`, not importable by name from outside
`client/`) -- consumers hold a `LuxClient` and reach its accessors, or its
`.sync` property for a synchronous ops surface (an applet's worker thread,
for example). `LuxHubClient` (`punt_lux.hub_client`) is unchanged and remains
public for callers that hold the listen leg directly.

| Old (transport-flavoured, synchronous) | New (facade, async) |
|----------------------------------------|---------------------|
| `LuxRestClient.connect()` (removed) | `LuxClient.connect()` |
| `LuxRestClient.for_identity(...)` (removed) | `LuxClient.for_identity(...)` |
| `client.render(req)` | `await client.scene.show(req)` |
| `client.render_table(req)` | `await client.scene.table(req)` |
| `client.render_dashboard(req)` | `await client.scene.dashboard(req)` |
| `client.update(sid, req)` | `await client.scene.update(sid, req)` |
| `client.clear_scene(sid)` | `await client.scene.clear(sid)` |
| `client.clear()` | `await client.scene.clear_all()` |
| `client.list_scenes()` | `await client.scene.ls()` |
| `client.inspect_scene(sid, facts=...)` | `await client.scene.inspect(sid, facts=...)` |
| `client.close_frame(fid)` | `await client.frame.close(fid)` |
| `client.list_menus()` | `await client.menu.ls()` |
| `client.set_menu(req)` | `await client.menu.set(req)` |
| `client.list_clients()` | `await client.session.ls()` |
| `client.identify(decl, scope=...)` | `await client.session.identify(decl)` |
| `client.register_callback(id, label)` | `await client.callback.register(id, label)` |
| `client.get_display_info()` | `await client.display.info()` |
| `client.get_theme()` | `await client.display.get_theme()` |
| `client.get_window_settings()` | `await client.display.get_window()` |
| `client.read_display_mode(repo)` | `await client.display.get_mode(repo)` |
| `client.screenshot()` | `await client.display.screenshot()` |
| `client.list_recent_events(count)` | `await client.event.ls(count)` |
| `client.list_errors(count)` | `await client.error.ls(count)` |
| `client.ping(wait)` | `await client.ping(wait)` |
| `client.listener(...)` | `client.listener(...)` (unchanged) |

## Connecting to `luxd`'s MCP endpoint directly

This is how the plugin connects, and a session configured by hand connects the
same way: straight to `luxd`'s HTTP endpoint (`http://127.0.0.1:8430/mcp`), with
no per-session process in the path. A copy-paste example is in
[`plugin/.claude-plugin/mcp-http.example.json`](../plugin/.claude-plugin/mcp-http.example.json).

Such a session gets the whole tool surface but owns no menu entries, because it
holds no connection a click could arrive on. Menu entries belong to the
session's **applets** — `lux-beads` and the like — which the session-start hook
launches and which hold their own listener; `register_callback` from the tool
surface is refused, saying so.

Start `luxd` first (`lux hub install` and start the service, or run `luxd` in a
terminal), then verify the direct connection end to end:

```bash
uv run python scripts/direct_connection_probe.py
```

The probe initializes a session, lists the tool surface, and calls a read-only
tool. `luxd` binds loopback only and refuses a non-loopback `--host` at
startup; remote access awaits authentication.
