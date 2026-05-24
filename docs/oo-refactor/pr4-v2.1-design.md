# PR 4 — io-model Hub, Element interaction, Agent Subscribe

**Status:** design
**Bead:** `lux-wb55`
**Worker / Evaluator:** `rmh` / `gvr`
**Consulted:** `dna` on Element behavior shape and DialogElement contract.
`mdm` on MCP tool surface. `djb` on Observer trust model. `rej` on Composite
and bound-callback pattern.

PR 4 lands four things at once:

1. The io-model Hub — a process that owns authoritative scene state, resolves
   wire-level interactions to Element instances, and dispatches handlers.
2. Two interaction-bearing Element kinds — `ButtonElement` and a composite
   `DialogElement` whose child Buttons self-wire to its own model methods.
3. A typed event subsystem on the Element ABC — `add_handler` /
   `remove_handler`, a dispatcher loop, and the canonical `ButtonClicked`
   event constructed at exactly one validation site.
4. The Agent Subscribe / Publish wire surface — per-connection topic scopes,
   snapshot-then-iterate fan-out, and a typed outbound `ObserverMessage`
   wire kind.

The work spans the Hub tier, the protocol package, and the MCP tool surface.
PR 3 shipped the foundation: Element ABC with `_emit`, the Renderer /
Decoder / Encoder Protocols, the sentinel-default `RendererFactory` /
`Emit` pattern, and the `_patch` template for in-place mutation. This PR
uses every piece of that foundation and adds the rest of the io-model.

## Guiding principle — no shims, no parallel paths

This design is legitimately complex: a distributed system, an event-driven
UI, event-driven communication across tiers and clients. The likelihood
of confusing ourselves and future readers is high. The discipline that
keeps the codebase legible is straightforward:

- No backwards-compatibility wrappers, alias shims, or "for now" branches
  that handle both an old and a new path.
- No retired class kept around because a single legacy caller still
  imports it.
- No parallel old / new code paths waiting for "the next PR" to remove the
  old one.
- Every caller of a renamed or replaced symbol migrates fully in the same
  PR that introduces the replacement.

The cost of making the design pristine on the way in is paid once. The
cost of carrying a shim is paid every time a future contributor reads
the codebase and has to discover which path is canonical and which is
legacy. The same discipline applies to readers of this document: when
the doc says a class is replaced, the old class is gone — there is no
fallback to read about.

## Module layout

The Hub lives in `domain/hub/`. The Hub is the asyncio-resident process
state that holds: an index of every Element by `(scene_id, element_id)`,
the connection registry mapping each open transport to its `connection_id`,
the per-connection event poll queues, the Agent Subscribe registry, and
the dispatcher that resolves wire interactions to Element handlers and
fires them. `domain/hub/` is the only package that may import asyncio
primitives — every other domain module stays loop-agnostic.

The Element ABC lives in `domain/element_abc.py` and carries the handler
registry, the dispatcher entry point, and the Observable property
machinery. The Element kinds — `ButtonElement`, `DialogElement`, the
existing `TextElement` — extend the ABC, add typed fields, and publish a
catalog of declarative handler factories.

```text
luxd process (single process; holds the Hub):
  src/punt_lux/
    domain/
      hub/                ← the io-model Hub: state, dispatch, Subscribe registry
      element_abc.py      ← Element ABC: handler registry, Observable mixin
      update.py           ← AddElement, RemoveElement, SetProperty (PR 3)
    protocol/
      elements/           ← per-kind wire classes + codecs
        button.py
        button_codec.py
        dialog.py
        dialog_codec.py
        text.py           (PR 3)
        text_codec.py     (PR 3)
      messages/
        interaction.py    ← inbound InteractionMessage (PR 3) + outbound ObserverMessage (PR 4)
    tools/                ← MCP entry point. Thin: in-process, calls Hub directly.
    applet/               ← Lux IPC entry point (PR 5 scaffold). Thin.
    display/              ← display server harness (PR 3 / PR 6)
    luxd.py               ← process entry point

Display process (separate, possibly remote):
  Connects to luxd's display transport.

Applet processes (separate, possibly remote — first one lands in PR 5):
  Wire: line-delimited JSON over TCP.
  Connects to luxd's applet/ endpoint.
```

The `tools/` and `applet/` packages do not own state. They are thin
adapters that translate transport-specific frames into Hub method calls.
Connection identity, locks, indexes, and the event loop all live in
`domain/hub/`. When a future PR adds a third transport (HTTP, gRPC,
anything), it adds another thin adapter in its own package and calls the
same Hub API.

The Hub's public surface is small and uniform across transports:

- `subscribe(connection_id, topic)` — register interest in a topic.
- `unsubscribe(connection_id, topic)` — drop registration.
- `publish(connection_id, topic, payload)` — fan out a business event to
  the caller's subscribers (scoping rules described in the Agent
  Subscribe section).
- `apply(connection_id, update)` — mutate authoritative scene state.
- `dispatch(connection_id, interaction)` — resolve an Element by
  `(scene_id, element_id)`, validate, fire matching handlers.
- `poll(connection_id, timeout)` — block for the next queued business
  event for this connection.

Adapters in `tools/` and `applet/` register and deregister connections
on transport setup and teardown. Everything else is a Hub call.

## Process topology

Three roles, three processes:

| Role | Where | What it does |
|------|-------|--------------|
| `luxd` | one host | holds the Hub, accepts MCP tool calls in-process, accepts applet TCP connections, drives the display transport |
| display | same or remote host | ImGui renderer; receives the rendered scene over the display transport |
| applet | same or remote host | a long-running consumer of business events; opens a TCP connection to luxd and holds it for its lifetime |

The applet transport is line-delimited JSON over TCP. The choice of TCP
is deliberate: the system is distributed by design, and an applet may
run on a different machine from luxd. AF\_UNIX remains acceptable as a
local-loopback optimization where both ends are on the same host, but
the wire shape and connection model are the same — the protocol does
not branch on transport.

Applets hold their TCP connection open bidirectionally for the
connection's lifetime. The Hub pushes business events on the same
connection the applet uses to send updates, subscribe, or publish. No
request / response close-between-calls, no reconnect-per-message. An
applet that wants to poll synchronously may do so via the same `poll`
call MCP uses, but the default async path is push over the open
connection.

MCP sessions are in-process. The `tools/` package runs inside the
`luxd` process and calls Hub methods directly. There is no MCP-to-luxd
network hop; the connection_id assigned to an MCP session is a
process-local handle.

The next sections describe the Element ABC's handler registry and
dispatch loop, the declarative handler catalog and wire format, the
composite component pattern that DialogElement embodies, the validated
`ButtonClicked` event and its single construction site, and the Agent
Subscribe / Publish subsystem with its per-connection scoping rule.
