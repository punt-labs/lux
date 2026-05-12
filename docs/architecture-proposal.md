# Design: Lux Architecture

**Author:** Alan T (adt)
**Date:** 2026-05-12
**Status:** PROPOSED

## Thesis

Lux is a performant X11-esque multi-process display architecture constrained to ImGui rendering for agents and apps. The protocol is transport-agnostic (Unix socket today, TCP when needed), which makes the architecture distributable across hosts without changing the wire format.

## The Question This Document Answers

Why is Lux built as three independent processes? Where could it go?

The companion document (`docs/mcp-proxy-proposal.md`) covers
implementation: new files, modified files, scenario walk-throughs,
migration plan. This document covers the architecture and its rationale.
Read this first for the "why," then the mcp-proxy proposal for the "how."


## Definitions

- **Display server**: The process that owns the screen. Renders element
  trees, routes input events back to clients. One per seat.
- **Daemon**: The process that holds session state, enforces policy,
  manages the application menu, and multiplexes client connections onto
  a single display. One per user.
- **Client**: Any process that sends element trees and receives events.
  Many per user. Any language that speaks the protocol.
- **Protocol**: Length-prefixed JSON over Unix socket (display leg) or
  WebSocket (daemon leg). The protocol is the API surface.
- **Seat**: A (user, display) pair. Today, one user has one display.
  Multi-monitor is future optionality.


## The X11 Analogy

Lux follows the X Window System's three-tier separation. The mapping is
direct:

```
X11 model                              Lux model

+------------------+                    +------------------+
|    X Client      |                    |   Lux Client     |
| (xterm, firefox) |                    | (Python, Go, sh) |
+--------+---------+                    +--------+---------+
         |  X protocol                           |  JSON protocol
+--------+---------+                    +--------+---------+
|  Window Manager  |                    |   lux serve      |
|  (i3, mutter)    |                    |   --daemon       |
+--------+---------+                    +--------+---------+
         |  X protocol                           |  JSON protocol
+--------+---------+                    +--------+---------+
|    X Server      |                    |   lux display    |
|  (Xorg, XWayland)|                    |   (ImGui)        |
+------------------+                    +------------------+
```

Each tier has a single responsibility:

| X11 | Lux | Responsibility |
|-----|-----|----------------|
| X Server | `lux display` | Rendering. Owns the framebuffer. Draws what clients describe. Routes input events back. Knows nothing about "applications" or "sessions." |
| Window Manager | `lux serve --daemon` | Policy. Session routing, scene ownership, menu registry, event dispatch. Adds the concept of applications on top of raw rendering. |
| X Client | Any Lux client | Application logic. Sends element trees, receives events. Any language that speaks the protocol. |

The X Server does not know what a "window manager" is. It renders
windows, accepts input, and routes events. The window manager is just
another client with special privileges. Similarly, the Lux display does
not know what a "daemon" is. It renders scenes, accepts connections, and
sends interaction events. The daemon is just the client that manages
policy.

One intentional departure from X11: the Lux daemon is managed by
launchd/systemd, not self-managed. An X11 window manager is launched
by the user or a session script; it has no system-level lifecycle
management. The Lux daemon is user-scoped infrastructure — it must
survive crashes (`KeepAlive=true`), start at login (`RunAtLoad=true`),
and be visible in `launchctl list` for diagnostics. This is a lifecycle
choice, not an architectural one: the daemon is still just a client
of the display.


## Three Processes, Three Roles

### lux display

The renderer. A single-threaded ImGui render loop with non-blocking
Unix socket IPC. It maintains:

- The element tree (scenes, frames, elements)
- Widget state (checkbox values, slider positions, text input buffers)
- The framebuffer (OpenGL via ImGui)

It does not maintain:

- Session identity (who sent a scene)
- Application menus (the daemon registers these)
- Display mode preferences (the daemon reads config)

The display accepts any client that connects to its Unix socket and
speaks length-prefixed JSON. It does not authenticate, does not track
session keys, does not enforce ownership. It is a shared canvas.

**Protocol**: Length-prefixed JSON over Unix domain socket. Message
types: Show, Update, Clear, Ping/Pong, Connect, Introspect,
ListScenes, Menu, Screenshot. Interaction events (button clicks, slider
changes, text input) flow back to the client that registered the
callback.

**Lifecycle**: User-scoped, long-lived. Starts at first need (daemon
auto-spawns it), runs until the user kills it or the machine shuts
down. Closing the window hides it; the process persists. Scenes
survive across show/hide cycles. This is the menu bar app model: the
window is ephemeral, the process is infrastructure.

### lux serve --daemon

The policy layer. A WebSocket server (Starlette + uvicorn) that
multiplexes MCP sessions onto a single display connection. It
maintains:

- Per-session state (event queues, menu registrations)
- Scene ownership (which session sent which scene)
- The application launcher (menu items that spawn subprocesses)
- Display mode config (`display=y|n`)

It does not maintain:

- The element tree (that is the display's job)
- Widget state (that is the display's job)
- The framebuffer (that is the display's job)

The daemon holds one `LuxClient` connection to the display. All
sessions share it. When Session A calls `show()`, the daemon forwards
the element tree to the display over the shared connection, then
records `scene_owner["dashboard"] = "A"`. When the display sends an
interaction event from that scene, the daemon routes it to Session A's
event queue.

**Protocol to display**: Length-prefixed JSON over Unix socket. Same
protocol any client would use.

**Protocol to clients**: WebSocket, MCP JSON-RPC. Each WebSocket
connection is one session, identified by `?session_key=<pid>`.

**Lifecycle**: User-scoped, long-lived. Managed by launchd (macOS) or
systemd (Linux) with `KeepAlive=true`. Starts at login, runs until
the user uninstalls the service. Independent of the display: the
daemon can run while the display is hidden or not yet spawned.

### Clients

Application code. Any process that wants to put something on screen.
Clients fall into two categories:

**MCP clients** connect to the daemon over WebSocket. They get session
isolation, event routing, and the full MCP tool surface (`show`,
`show_table`, `show_dashboard`, `recv`, etc.). Claude Code agents are
MCP clients. The mcp-proxy bridges stdio to WebSocket so Claude Code
can reach the daemon.

**Direct clients** connect to the display over Unix socket, bypassing
the daemon. They get raw rendering with no session isolation and no
event routing. A Go service that shows a dashboard, a shell script
that pipes JSON via `socat`, a C++ monitoring tool -- all valid direct
clients. The display accepts any connection.

**Protocol**: Depends on the connection path. MCP JSON-RPC over
WebSocket (via daemon) or length-prefixed JSON over Unix socket
(direct to display).

**Lifecycle**: Varies. Short-lived (a CLI command that sends one scene
and exits) or long-lived (a daemon that continuously updates a
dashboard). The display and daemon are indifferent to client lifetime.
Scenes persist after the client disconnects.


## Cardinality

| Process | Current | Future optionality |
|---------|---------|-------------------|
| `lux display` | 1 per user | M per user (multi-monitor, each display on a different seat) |
| `lux serve --daemon` | 1 per user | M per user (e.g., separate daemons for work and personal contexts, each with its own session state and display preferences) |
| Clients | N per user | N per user, any language |
| mcp-proxy | 1 per Claude Code session | Transport plumbing, not a tier. Scales with sessions. |

The common deployment: 1 display, 1 daemon, 5-10 clients. The
architecture does not prevent other ratios, but we are not building
for them now.


## The Protocol Is the API Surface

X11's lasting contribution was not Xlib or Xt or Motif. It was the X
protocol. Any language that could format X protocol messages could be
an X client. Xlib was C. XCB was C with explicit async. Qt, GTK,
Tk -- all different client libraries, all speaking the same wire
format.

Lux follows this principle. The protocol is length-prefixed JSON over
a socket. Any process that can:

1. Open a Unix domain socket (or TCP socket, in the future)
2. Write a 4-byte big-endian length prefix
3. Write a JSON object

...is a Lux client. No Python required. No MCP required. No daemon
required.

**Python** (current): `LuxClient` in `punt_lux/client.py`. Context
manager, typed methods, background listener thread.

**Go** (future, straightforward): `net.Dial("unix", path)`, encode
JSON, write length prefix. ~50 lines for a working client.

**Shell** (works today): `socat` or `nc` with a length-prefix wrapper.
Useful for one-shot dashboards from cron jobs or monitoring scripts.

**MCP** (current): The `lux serve` MCP server is one projection of
the protocol. It adds convenience (scene framing, display mode
management, event polling) but is not the only way to drive the
display. An MCP tool call to `show()` eventually becomes a
length-prefixed JSON message on the Unix socket -- the same message a
Go client would send directly.


## The Launcher Pattern

The daemon does not run application logic. It registers menu items and
spawns subprocesses on click:

```
Applications menu (rendered by the display, registered by the daemon)
  |
  +-- Beads Browser    -> spawns: lux show beads
  +-- System Monitor   -> spawns: lux show monitor
  +-- [future app]     -> spawns: lux show <name>
```

The flow:

1. Daemon starts. Reads the application registry (config or
   convention).
2. Daemon sends menu registration messages to the display.
3. User clicks "Beads Browser" in the display's menu bar.
4. Display sends an interaction event to the daemon.
5. Daemon spawns `lux show beads` as a subprocess.
6. The subprocess connects to the display (via the daemon or
   directly), sends the beads scene, and exits.
7. The scene persists on the display. The subprocess is gone.

New applications are config entries, not code changes to the daemon.
The daemon is thin: menu registry + subprocess spawner + session
multiplexer.

Edge cases: if the subprocess crashes, the daemon logs the error and
takes no further action — the scene was either sent (persists on
display) or not (nothing to clean up). If the user clicks the same
menu item while a subprocess is still running, the daemon spawns a
second instance; the new scene replaces the old one on the display
(same `scene_id`). No deduplication needed — the display handles
scene replacement idempotently.

This is the Postern model applied to the display layer. Postern keeps
a live Pharo image running and accepts work over HTTP. The Lux daemon
keeps the display alive and accepts work over WebSocket. Both are
infrastructure that outlives any single client interaction.


## Display Lifecycle

The display process behaves like a macOS menu bar app:

| User action | Effect |
|-------------|--------|
| `lux show` | Bring window to front. Spawn display if not running. |
| `lux hide` | Hide window. Process stays running. Scenes persist. |
| Click window close button | Same as `lux hide`. |
| Machine shutdown | Process exits. launchd/systemd does not restart it (display requires a GPU context). |
| `lux display --restart` | Kill and re-spawn. Scenes are lost (they lived in process memory). |

The display process is long-lived infrastructure: login to shutdown.
The window is ephemeral: shown when there is output to see, hidden
when dismissed. Scenes survive across show/hide cycles because the
process is alive and the element tree is in memory. Scenes do NOT
survive display restarts — the element tree lives in process memory
and is lost on crash or `lux display --restart`. Clients must re-send
scenes after a display restart.

The daemon calls `ensure_display()` on first need. Once the display is
running, the daemon does not manage its lifecycle further. If the
display crashes, the daemon detects the broken socket on the next tool
call, re-spawns it, and reconnects.


## Remote Display

### Immediate goal

Local and remote agents, unified display. An agent on Host B (SSH)
renders on Host A (the user's Mac).

```
Host B (remote)                          Host A (local)

Claude Code                              lux serve --daemon
    |                                        |
    +-- mcp-proxy --WebSocket------->--------+
         (via SSH reverse tunnel             |
          -R 8430:127.0.0.1:8430)    lux display (ImGui)
```

The SSH tunnel makes the daemon's WebSocket port available on Host B
as `localhost:8430`. The proxy on Host B connects to what looks like a
local daemon but is actually Host A's daemon through the tunnel.

No code changes to the display or daemon. The tunnel is transparent.

### Three-host optionality

The architecture permits separating the three processes across three
hosts. The daemon-to-display leg today uses a Unix domain socket
(local only). Adding TCP transport on that leg would allow:

```
Host C (cloud agent)     Host B (persistent server)     Host A (user's Mac)

mcp-proxy --WS-->        lux serve --daemon --TCP-->     lux display
```

We are not building this now. The architecture does not prevent it.
The Unix socket can be replaced with a TCP socket in `LuxClient` and
`display.py` without changing the protocol (same length-prefixed JSON,
different transport). The daemon would need a `--display-host` flag.

The constraint is latency: ImGui renders at 60fps, and the
daemon-to-display leg carries element trees that can be tens of KB.
Over LAN this is fine. Over WAN it depends on the update frequency.
This is a measurement question, not an architecture question.


## `lux y|n` Semantics

`lux y` and `lux n` are per-repo agent preferences. They are stored in
`.punt-labs/lux.md` inside the repo and read by the Lux plugin skill
layer on the agent host.

What `lux y` means: "In this repo, the agent should use Lux display
tools."

What `lux n` means: "In this repo, the agent should not call Lux
display tools."

What neither means: anything about the display process or the daemon.
Those are user-level infrastructure. Two repos can have different
settings. The daemon does not read `.punt-labs/lux.md` -- the skill
layer does.

Enforcement is at the call site:

- `lux n`: The plugin skill suppresses MCP tool calls (`show`,
  `show_table`, etc.). The daemon never sees them.
- `lux y`: The plugin skill allows MCP tool calls. The daemon processes
  them normally.

The daemon's display connection is unaffected by `lux y|n`. If the
display is connected, it stays connected. If it is not connected,
`lux y` triggers `ensure_display()` on the first `show()` call.

This separation matters for remote display. The daemon runs on Host A
where the display is. The `.punt-labs/lux.md` file lives in the repo
on Host B. The daemon on Host A cannot read Host B's filesystem. The
skill layer on Host B is the correct enforcement point.


## Applications Without Agents

The Beads Browser works when no Claude Code session is running:

1. The daemon is alive (launchd started it at login).
2. The display is alive (the daemon spawned it earlier, or the user
   ran `lux show`).
3. The user clicks "Beads Browser" in the Applications menu.
4. The daemon spawns `lux show beads`.
5. The subprocess queries DoltDB, sends the beads scene to the
   display, and exits.
6. The user sees the beads browser. No MCP, no proxy, no agent.

This is the Postern model: the system is alive and useful without
external drivers. Postern keeps a Pharo image running; Lux keeps a
display server running. Both are infrastructure that serves whoever
connects -- agent or human.

This property is load-bearing for adoption. If Lux only works when
Claude Code is running, it is a terminal extension. If Lux works
independently, it is a display system that agents happen to use. The
second framing is correct and the architecture must preserve it.


## Relationship to the MCP-Proxy Proposal

The mcp-proxy proposal (`docs/mcp-proxy-proposal.md`) is Phase 1 of
implementing this architecture. It covers:

- The daemon process (`daemon.py`, `service.py`)
- Session multiplexing (`server.py` refactor)
- Transport bridging (`mcp-proxy` + `plugin.json`)
- The installation and migration path

This document provides the architectural context that the mcp-proxy
proposal assumes. The mcp-proxy proposal answers "what do we build and
in what order?" This document answers "why is Lux built this way and
where could it go?"

After the mcp-proxy proposal ships, the architecture described here is
fully realized for the local case. Remote display requires only an SSH
tunnel and a proxy config on the remote host -- no additional code.
Multi-host display (three processes on three hosts) requires TCP
transport on the daemon-to-display leg, which is additive.


## What We Build Now vs. What Is Optionality

### Building now (via the mcp-proxy proposal)

- Three-process separation: display, daemon, proxy
- Session multiplexing with per-session state isolation
- launchd/systemd service management for the daemon
- Application launcher (menu registry + subprocess spawning)
- Display show/hide lifecycle (menu bar app model)
- Local + remote display (SSH tunnel, no code changes)

### Optionality (architecture permits, not building)

- Multi-monitor (M displays per user)
- Multi-tenant (M daemons per user)
- TCP transport on the daemon-to-display leg (three-host model)
- Go / C++ / shell client libraries (protocol is stable, libraries
  are straightforward)
- Authentication on the display socket. Current trust model: any
  process running as the same UID can connect and draw. This is the
  same trust boundary as X11 with `xhost +local:` — deliberate for
  local use, insufficient for network-exposed sockets. TCP transport
  would require auth (Bearer token or TLS client cert).
- Display process managed by launchd (currently managed by the daemon
  via `ensure_display()`)


## Summary

Lux is three processes with three roles, connected by a JSON protocol.
The display renders. The daemon manages policy. Clients send scenes.
The protocol is the API surface -- not the MCP layer, not the Python
library.

This is the X11 model applied to agent display: a renderer that
accepts any client, a policy layer that adds sessions and menus, and
clients in any language. The immediate value is solving dev restarts,
session duplication, and remote display. The architectural value is a
display system that outlives any single agent session and serves anyone
who speaks JSON over a socket.
