# Design: Lux MCP Proxy Architecture (v2)

**Author:** Alan T (adt)
**Date:** 2026-05-11
**Status:** PROPOSED
**Supersedes:** `.tmp/design-mcp-proxy.md` (v1)

## Problem Statement

Three operational problems stem from one architectural root cause: Claude Code owns the MCP server process lifecycle via stdio, while the display server is a long-lived singleton. The coupling between a session-scoped process (`lux serve`) and a user-scoped process (`lux display`) creates friction at every boundary.

**Problem 1 -- Dev restarts.** A code change to `display.py` or `server.py` requires killing the display, restarting Claude Code (which re-spawns `lux serve`), and re-enabling display mode. The agent cannot restart its own MCP server. In a typical iteration cycle this adds 30-60 seconds per change.

**Problem 2 -- Session duplication.** Each Claude Code session spawns its own `lux serve` via stdio. Five sessions produce five MCP servers, five `LuxClient` instances connecting to the same Unix socket, and five copies of menu registrations. The display server handles this (it accepts multiple clients), but the overhead is pure waste: five processes, five sets of retry loops, five eager-connect handshakes.

**Problem 3 -- Remote display.** An agent running on Host B (SSH) has no path to a display on Host A (local machine). The Unix socket transport is local-only. The user runs agents locally and remotely and wants a unified display — all agents project onto the same screen.

## Definitions

- **mcp-proxy**: A ~6 MB Go binary that bridges MCP stdio transport to a WebSocket endpoint. Claude Code spawns it instead of the real MCP server. It forwards JSON-RPC messages opaquely.
- **daemon**: The long-lived process that holds state and serves MCP over WebSocket. In Lux's case, this is `lux serve` running in daemon mode.
- **display server**: The ImGui render loop (`lux display`) that listens on a Unix domain socket and draws frames.
- **session**: One Claude Code window/tab. Each session gets its own stdio pipe to its proxy instance, which gets its own WebSocket connection to the daemon.
- **session_key**: A query parameter on the WebSocket URL that identifies a session. The daemon uses it for per-session state isolation (event routing, menu registrations). Follows Quarry's pattern (see `quarry/http_server.py:1317`).

## Architecture

### Current

```
Claude Code --stdio--> lux serve --Unix socket--> lux display
  (session)             (per-session)               (singleton)
```

### Proposed

```
Claude Code --stdio--> mcp-proxy --WebSocket--> lux serve --Unix/TCP--> lux display
  (transport             (session state            (renderer)
   bridge)                server)
```

Three processes, three roles:

| Process | Role | What it owns |
|---------|------|-------------|
| mcp-proxy | Transport bridge | stdio ↔ WebSocket. Stateless. Replaceable. |
| lux serve --daemon | Session state server | Session isolation, event routing, scene ownership, menu tracking, display mode. The authority for all agent state. |
| lux display | Renderer | ImGui render loop, element tree, widget state, framebuffer. Pure rendering — draws what it's told. |

The separation is justified by three properties:

1. **Independent lifecycles.** The proxy is session-scoped (Claude Code spawns it). The daemon is user-scoped (launchd manages it). The display is window-scoped (runs while the user wants a window). Each restarts without affecting the others.

2. **Independent deployment.** Today all three run on one host. The architecture allows them to separate: proxy on Host A (cloud agent), daemon on Host B (persistent server), display on Host C (user's Mac). The immediate goal is local + remote agents with a unified display. The optionality for multi-host and multi-user is preserved by the separation, not required by it.

3. **Independent protocols.** Proxy ↔ daemon speaks WebSocket (MCP JSON-RPC). Daemon ↔ display speaks length-prefixed JSON over Unix socket (or TCP when needed). Neither protocol leaks into the other layer.

### Process inventory (5 sessions, single host)

| Component | Current | Proposed |
|-----------|---------|----------|
| mcp-proxy | 0 | 5 (~6 MB each, <10 ms startup) |
| lux serve | 5 (Python, ~40 MB each) | 1 |
| lux display | 1 | 1 |
| Total processes | 6 | 7 |
| Total memory | ~200 MB + display | ~70 MB + display |

Net memory drops because four redundant Python MCP servers are eliminated. The proxy processes are lightweight (Go static binary, no Python import overhead).


## User Model: Display Window Lifecycle

The display process behaves like a macOS menu bar app: closing the window hides it, it does not kill the process. Scenes persist, events still queue. The display stays connected to the daemon.

| Command | Effect |
|---------|--------|
| `lux show` | Bring the display window to front (unhide). If display process not running, spawn it. |
| `lux hide` | Hide the display window. Process stays running, scenes persist. |
| Window close button (×) | Same as `lux hide` — hides, does not kill. |

The daemon calls `ensure_display()` on the first `show()` MCP call. Once the display is running, it stays running until the user explicitly kills it or the machine shuts down. The window appears and disappears via show/hide — no process restart, no scene loss, no reconnection overhead.

This model means:
- The display process is long-lived (login to shutdown), same as the daemon.
- The window is ephemeral (shown when agents have output, hidden when the user dismisses it).
- `lux show` and `lux hide` are CLI commands routed to the display via the daemon's Unix/TCP socket.
- No menu bar icon for now — future option when warranted.

## Resolved Design Decisions

### Decision 1: `display=n` with daemon

**Decision: (c) Daemon always runs, but defers display connection until first `show()` with `display=y`.**

The daemon is a WebSocket server that costs ~40 MB at idle. When `display=n`, it serves MCP tools normally but does not call `ensure_display()` and does not open a Unix socket connection to the display. The first call to `set_display_mode("y")` -- or `show()` when `display=y` -- triggers the display connection and auto-spawn.

Why not (a): "Daemon always runs, `show()` returns silent ack when display=n" means every `show()` call in `n` mode still traverses the full tool path and returns a fake ack that could confuse agents expecting real rendering.

Why not (b): "No daemon when display=n" defeats the purpose. The daemon must be running before the proxy can connect. If the daemon is not running, the proxy has no WebSocket endpoint and Claude Code's MCP server fails to initialize. The proxy has no "offline" mode -- it either connects or it is not running.

The daemon process is always started by `lux ensure-daemon`. Whether it connects to a display depends on the config at startup and `set_display_mode()` calls during the session.

**Canonical invariant:** The daemon's display connection, once established, is never torn down by the daemon. It persists until the daemon exits or the display process dies. `display=n` only prevents the initial eager connection — it does not sever an existing one. The first `show()` call or `set_display_mode("y")` call triggers the connection, whichever comes first. If the daemon restarts while `display=n`, it does not connect to the display on startup, even if a display process is already running.

### Decision 2: Remote `/lux y|n`

**Decision: (a) In remote mode, display mode is always on. The skill layer on the agent host suppresses MCP calls when the user invokes `/lux n`.**

Rationale: The daemon runs on Host A where the display is. Host A has no per-repo `.punt-labs/lux.md` -- that file lives in the repo on Host B. The daemon on Host A cannot read Host B's filesystem. The user who set up the SSH tunnel did so intentionally; they want display.

The Lux plugin skill on Host B respects `.punt-labs/lux.md` locally: when `display=n`, the skill does not call `show()`, `show_table()`, etc. This is enforcement at the call site, not at the daemon. No new MCP tool is needed.

If the user on Host B runs `/lux n`, the skill stops calling display tools. The daemon on Host A stays connected to the display (no-op). When the user runs `/lux y`, the skill resumes calling display tools. The daemon on Host A renders immediately because the display connection was never dropped.

### Decision 3: Menu registrations with shared daemon

**Decision: Per-session menu registrations tracked by `session_key`, cleaned up on WebSocket disconnect.**

The daemon maintains a `dict[str, set[str]]` mapping `session_key` to the set of menu item IDs registered by that session. On WebSocket disconnect, the daemon:

1. Looks up the session's registered menu items.
2. Calls `client.unregister_menu_item(item_id)` for each.
3. Removes the session entry from the tracking dict.

On daemon restart, all registrations are lost (the display server clears per-client state when a client disconnects). Each session re-registers via its lifespan handler when the proxy reconnects and the MCP session re-initializes.

This mirrors Quarry's `session_key` isolation pattern (`quarry/http_server.py:1317-1329`): each WebSocket connection = one session = isolated state.

### Decision 4: Scene ownership across sessions

**Decision: Scenes are shared. All sessions see all scenes. `owner_fd` is removed from `list_scenes` output in favor of `owner_session`.**

The display server is a shared canvas. Session 1 sends a scene; session 2 can `inspect_scene` and see it. This is the correct behavior: the display is the user's screen, and all agents contribute to it.

The current `owner_fd` field in `list_scenes` refers to the Unix socket file descriptor. With a shared daemon, there is only one fd (the daemon's). The field becomes meaningless.

Replace `owner_fd` with `owner_session` (the `session_key` of the WebSocket connection that sent the scene). The daemon tracks this in its `scene_owner` dict (daemon-side, not display-side). The `list_scenes` MCP tool in `server.py` enriches the display server's response with `owner_session` from the daemon's dict before returning to the caller — the display server's Unix socket protocol does not change. If the session disconnects, scenes persist on the display (the user might still be looking at them), but `owner_session` shows the originator.

### Decision 5: Host A startup for remote display

**Decision: `lux serve --daemon` on Host A, SSH reverse tunnel, `mcp-proxy` on Host B. Step by step below in Scenario 5.**

The user on Host A (local Mac) runs two things:
1. `lux ensure-daemon` -- starts the daemon if not running.
2. `ssh -R 8430:127.0.0.1:8430 host-b` -- creates the reverse tunnel.

The display auto-spawns when the agent's first `show()` call arrives through the tunnel. No manual `lux display` needed.


## Implementation Components

### New files

| File | Purpose | ~Lines | Quarry equivalent |
|------|---------|--------|-------------------|
| `src/punt_lux/service.py` | launchd/systemd registration for daemon | ~350 | `quarry/service.py` (573 lines) |
| `src/punt_lux/daemon.py` | WebSocket server (Starlette + uvicorn), session multiplexing, `/health`, `/mcp` | ~250 | `quarry/http_server.py` (route setup + WebSocket handler) |
| `src/punt_lux/remote.py` | `write_proxy_config()`, `read_proxy_config()` for `~/.punt-labs/mcp-proxy/lux.toml` | ~80 | `quarry/remote.py` (93 lines) |

### Modified files

| File | Changes |
|------|---------|
| `src/punt_lux/server.py` | Extract session state into a class. Add `run_mcp_session()` function that `daemon.py` calls per WebSocket. Keep `mcp.run(transport="stdio")` as the direct-mode entry point. |
| `src/punt_lux/__main__.py` | Add `ensure-daemon`, `daemon-status` subcommands. Add `--daemon` flag to `serve`. |
| `src/punt_lux/paths.py` | Add `daemon_pid_path()`, `daemon_port_path()`, `daemon_log_path()` functions alongside existing display helpers. |
| `.claude-plugin/plugin.json` | Command changes to `sh -c` wrapper with fallback. |
| `install.sh` | Add mcp-proxy installation, daemon service registration, proxy config creation. |

### Session state isolation

Following Quarry's ContextVar pattern (`quarry/mcp_server.py:76`):

```python
# In server.py
_session_key: ContextVar[str] = ContextVar("session_key", default="local")
```

Each WebSocket connection sets `_session_key` before entering the MCP session. Tools that need per-session behavior (event routing, menu tracking) read it. Tools that operate on the shared display (`show()`, `clear()`, `inspect_scene()`) use the shared `LuxClient` directly.

The `recv()` tool is the critical case: it must return events only for the calling session. The daemon maintains a per-session event queue (`dict[str, asyncio.Queue[InteractionMessage]]`). When the display sends an event, the daemon routes it to the session that registered the callback. If no session matches (e.g., a menu click on a shared menu item), it goes to the session whose `session_key` matches the `owner_session` of the scene.

**Async blocking.** The daemon runs in uvicorn (async). `recv(timeout)` cannot call `queue.Queue.get(timeout)` — that blocks the event loop. Instead, the per-session queue is `asyncio.Queue`, and the `recv()` MCP tool handler uses `asyncio.wait_for(session_queue.get(), timeout=timeout)`. This is native async, no thread executor needed.

**Orphaned-scene events.** When a session disconnects, its scenes persist on the display (the user may still be looking at them). If the user clicks a button in an orphaned scene, the daemon receives the event but the owning session's queue no longer exists. Decision: **drop the event and log a debug message.** The scene is orphaned — no session is listening. If another session later sends a scene with the same `scene_id`, it becomes the new owner and future events route to it.

### daemon.py structure

```python
# Starlette ASGI app
async def _mcp_websocket_route(websocket: WebSocket) -> None:
    """Per Quarry pattern: auth check, session_key extraction, isolated MCP session."""
    # 1. CSWSH origin check
    # 2. Bearer token check (if configured)
    # 3. Extract session_key from ?session_key= query param
    # 4. Register session state (event queue, menu registrations)
    # 5. async with websocket_server(...) as (read, write): await run_mcp_session(read, write)
    # 6. finally: cleanup session state (unregister menus, drain event queue)

async def _health_route(request: Request) -> Response:
    """Returns 200 with {"status": "ok", "sessions": N, "display": bool}."""

def create_app(token: str | None = None) -> Starlette:
    """Build the ASGI app with routes and CORS middleware."""

def serve(host: str = "127.0.0.1", port: int = 8430, token: str | None = None) -> None:
    """Entry point: run uvicorn with the app. Write port file. Clean up on shutdown."""
```

### remote.py structure

Follows `quarry/remote.py` exactly:

```python
MCP_PROXY_CONFIG_PATH = Path.home() / ".punt-labs" / "mcp-proxy" / "lux.toml"

def write_proxy_config(url: str, token: str | None = None) -> None:
    """Write [lux] section to mcp-proxy config. Atomic write, chmod 0600."""

def read_proxy_config() -> dict[str, Any]:
    """Return parsed config or {} if absent."""
```

### service.py structure

Follows `quarry/service.py` structure. Key differences:
- Label: `com.punt-labs.lux` (Quarry uses `com.punt-labs.quarry`)
- Binary: `~/.local/bin/lux serve --daemon --port 8430`
- No TLS (SSH tunnel provides encryption for remote)
- No env file needed (no API key by default)
- Simpler plist: no EnvironmentVariables section, just ProgramArguments + KeepAlive

```python
_LABEL = "com.punt-labs.lux"
_LAUNCHD_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{_LABEL}.plist"
_SYSTEMD_UNIT = Path.home() / ".config" / "systemd" / "user" / "lux.service"

def install() -> str: ...
def uninstall() -> str: ...
```

### plugin.json

Following Quarry's exact pattern (`quarry/.claude-plugin/plugin.json:13-16`):

```json
{
  "mcpServers": {
    "lux": {
      "type": "stdio",
      "command": "sh",
      "args": [
        "-c",
        "if command -v mcp-proxy >/dev/null 2>&1 && [ -f \"${HOME}/.punt-labs/mcp-proxy/lux.toml\" ] && grep -q '^\\[lux\\]' \"${HOME}/.punt-labs/mcp-proxy/lux.toml\"; then exec mcp-proxy --config lux; else exec lux serve; fi"
      ]
    }
  }
}
```

Three conditions, all required for proxy mode:
1. `mcp-proxy` binary exists on PATH
2. Config file `~/.punt-labs/mcp-proxy/lux.toml` exists
3. Config file contains a `[lux]` section

If any condition fails: fall back to `exec lux serve` (current direct mode). This preserves backward compatibility.

The `lux ensure-daemon` call is NOT in the plugin.json one-liner. The daemon is managed by launchd/systemd (installed by `install.sh`). The proxy connects to an already-running daemon. If the daemon is down, the proxy fails to connect and Claude Code reports the MCP server as unavailable -- this is the correct behavior (the user needs to start the daemon, not have it silently auto-started by a shell wrapper with no service management).

### Port selection

Default: `8430`. Resolution order:
1. `$LUX_SERVE_PORT` environment variable
2. Default `8430`

The daemon writes the bound port to `~/.punt-labs/lux/serve.port` after binding. The `ensure-daemon` command reads this file to verify the daemon is healthy. The proxy config (`lux.toml`) uses the configured port.

Port collision: If `8430` is in use, the daemon fails to bind and exits with a clear error message. The user sets `$LUX_SERVE_PORT` to override. The `ensure-daemon` command does NOT support ephemeral port selection -- a stable port is required for the proxy config and SSH tunnel.


## Scenario Walk-throughs

### Scenario 1: Fresh install, local, first time

**Precondition:** User has `uv` and `claude` CLI. No Lux installed.

1. User runs `install.sh` (downloaded from GitHub or via marketplace).
2. `install.sh` runs `uv tool install punt-lux` -- installs `~/.local/bin/lux`.
3. `install.sh` checks for `mcp-proxy`:
   - If absent: `curl -fsSL https://github.com/punt-labs/mcp-proxy/releases/.../install.sh | sh` installs it.
4. `install.sh` calls `lux install` (new CLI subcommand):
   - Writes launchd plist to `~/Library/LaunchAgents/com.punt-labs.lux.plist` with `KeepAlive=true`, `RunAtLoad=true`.
   - Loads the plist: `launchctl load -w <path>`.
   - Daemon starts, binds `ws://127.0.0.1:8430/mcp`, writes `~/.punt-labs/lux/serve.port`.
5. `install.sh` calls `lux setup-proxy` (writes `~/.punt-labs/mcp-proxy/lux.toml`):
   ```toml
   [lux]
   url = "ws://127.0.0.1:8430/mcp"
   ```
6. `install.sh` health-checks the daemon: `curl -fs http://127.0.0.1:8430/health` with retry loop (10 attempts, 2s apart).
7. `install.sh` registers marketplace and installs plugin (same pattern as Quarry's `install.sh` steps 7-9).
8. User opens Claude Code. Plugin loads.
9. Plugin.json runs: detects mcp-proxy + lux.toml + `[lux]` section. Runs `exec mcp-proxy --config lux`.
10. Proxy connects to `ws://127.0.0.1:8430/mcp?session_key=<PID>`.
11. Agent calls `set_display_mode("y")`.
12. Daemon reads config, calls `ensure_display()`, spawns `lux display`, connects via Unix socket.
13. Agent calls `show(...)` -- proxy forwards to daemon, daemon sends to display.

### Scenario 2: Returning user, local

**Precondition:** Lux was installed previously. Machine was rebooted.

1. At login, launchd starts `lux serve --daemon` (KeepAlive + RunAtLoad).
2. Daemon binds `ws://127.0.0.1:8430/mcp`, writes port file.
3. User opens Claude Code.
4. Plugin.json runs: detects mcp-proxy + lux.toml. Runs `exec mcp-proxy --config lux`.
5. Proxy connects to daemon's WebSocket.
6. If `display=y` in `.punt-labs/lux.md`: daemon's lifespan already connected to display (or auto-spawned it).
7. Agent sends MCP calls. Everything works.

Total time from Claude Code open to first tool call: <200 ms (proxy startup ~10 ms, WebSocket connect ~5 ms).

### Scenario 3: User types `/lux y` (display was off)

**Precondition:** Daemon is running, connected to proxy. `display=n` in config. No display process.

1. Skill calls `set_display_mode("y")` MCP tool.
2. Proxy forwards to daemon via WebSocket.
3. Daemon's `set_display_mode()` handler:
   a. Writes `display: "y"` to `.punt-labs/lux.md` via `write_field()`.
   b. Calls `_get_client()` which calls `ensure_display()`.
   c. `ensure_display()` spawns `lux display` (no PID file found, or process dead).
   d. Waits up to 5s for display socket to appear.
   e. Connects `LuxClient` to display via Unix socket.
   f. Calls `_setup_apps(client)` to register menu items.
4. Returns `"display:on"`.
5. Subsequent `show()` calls render to the now-connected display.

### Scenario 4: User types `/lux n` (display was on)

**Precondition:** Daemon is running, connected to display. `display=y` in config.

1. Skill calls `set_display_mode("n")` MCP tool.
2. Daemon's `set_display_mode()` handler:
   a. Writes `display: "n"` to `.punt-labs/lux.md` via `write_field()`.
   b. Does NOT disconnect from the display. The Unix socket connection stays open.
3. Returns `"display:off"`.
4. Subsequent `show()` calls still succeed (display connection is live).
5. The display mode flag is advisory -- consumer plugins (beads, biff) read it to decide whether to call display tools. The daemon does not enforce it.

This matches current behavior exactly. The daemon does not kill the display process or close its connection. The display stays available for the next `/lux y`.

### Scenario 5: Remote -- agent on Host B, display on Host A

**What the user does on Host A (local Mac with display):**

1. Verify Lux is installed: `lux --version`.
2. Verify daemon is running: `lux daemon-status`.
   - If not running: `lux ensure-daemon`.
   - If the daemon was installed via `install.sh`, launchd already started it.
3. SSH to Host B with reverse tunnel:
   ```
   ssh -R 8430:127.0.0.1:8430 host-b
   ```
   This binds `localhost:8430` on Host B to the daemon on Host A.

**What the user does on Host B (remote, in the SSH session):**

4. Install Lux if needed: `uv tool install punt-lux`.
5. Install mcp-proxy if needed: same as step 3 in Scenario 1.
6. Write proxy config manually (no `install.sh` on remote -- the daemon runs on Host A):
   ```
   mkdir -p ~/.punt-labs/mcp-proxy
   cat > ~/.punt-labs/mcp-proxy/lux.toml << 'EOF'
   [lux]
   url = "ws://127.0.0.1:8430/mcp"
   EOF
   chmod 600 ~/.punt-labs/mcp-proxy/lux.toml
   ```
   Or: `lux setup-proxy --url ws://127.0.0.1:8430/mcp` (convenience command).
7. Do NOT run `lux install` on Host B -- no daemon needed here. The proxy connects through the tunnel to Host A's daemon.

**What happens at runtime:**

8. User opens Claude Code on Host B.
9. Plugin.json runs: detects mcp-proxy + lux.toml. Runs `exec mcp-proxy --config lux`.
10. Proxy connects to `ws://127.0.0.1:8430/mcp` -- which, via SSH tunnel, reaches Host A's daemon.
11. Agent calls `show(...)`. Proxy sends to daemon on Host A. Daemon sends to display on Host A. User sees the rendering on their local Mac.

**When the SSH session ends:**

12. Tunnel closes. Proxy loses WebSocket connection.
13. Proxy detects disconnect via keepalive (5s ping, 2s pong timeout). Retries with exponential backoff (250 ms to 5s cap).
14. Display on Host A is unaffected. Scenes persist.
15. User re-establishes SSH with `-R 8430:...`. Proxy reconnects within 5s. Agent resumes.

### Scenario 6: Agent calls `show()` then `recv()` from two different sessions

**Precondition:** Two Claude Code sessions (A and B), each with its own proxy, both connected to the daemon.

**show() from Session A:**

1. Session A's proxy sends `show(scene_id="dashboard", ...)` over its WebSocket.
2. Daemon receives on Session A's WebSocket handler (which set `_session_key = "A"`).
3. Daemon calls `_get_client().show("dashboard", ...)` on the shared LuxClient.
4. Daemon records `scene_owner["dashboard"] = "A"`.
5. Display renders the scene. Returns ack to daemon. Daemon returns ack through Session A's WebSocket.

**recv() from Session B:**

6. Session B's proxy sends `recv(timeout=1.0)` over its WebSocket.
7. Daemon receives on Session B's WebSocket handler (`_session_key = "B"`).
8. Daemon checks Session B's event queue. It is empty.
9. After 1.0s timeout, returns `"none"`.

**recv() from Session A (after user clicks a button in Session A's scene):**

10. Display sends an interaction event (button click in scene "dashboard") to the daemon's LuxClient.
11. Daemon's listener thread receives the event. Looks up `scene_owner["dashboard"]` = "A".
12. Routes the event to Session A's event queue.
13. Session A calls `recv()`. Daemon checks Session A's event queue. Finds the button click. Returns it.

**Key invariant:** Events route to the session that owns the scene. If a scene was sent by Session A, only Session A receives interaction events from that scene. Session B calling `recv()` never sees Session A's events.

### Scenario 7: Developer changes server.py and wants to test

**Precondition:** Developer is working in the Lux repo. Daemon is running via launchd. Proxy is connected.

1. Developer edits `src/punt_lux/server.py`.
2. Developer runs: `lux ensure-daemon --restart` (new CLI flag).
   - `ensure-daemon --restart` sends SIGTERM to the daemon PID (read from `~/.punt-labs/lux/serve.pid`).
   - Daemon shuts down: closes WebSocket connections (proxies see disconnect), disconnects from display.
   - launchd's `KeepAlive=true` restarts the daemon automatically with the new code.
   - `ensure-daemon --restart` waits for the health endpoint to respond (up to 10s).
3. Proxies detect WebSocket disconnect. Begin reconnect backoff.
4. Daemon restarts (launchd respawn), binds WebSocket, writes port file.
5. Proxies reconnect within 5s. MCP sessions re-initialize. Lifespan handlers run (eager connect if `display=y`).
6. New code is live.

**Total downtime:** 2-5 seconds (daemon restart + proxy reconnect). Compare to current: 30-60 seconds (kill display, restart Claude Code, re-enable display mode).

**What stays running:** The display process (`lux display`) is not restarted. Scenes on screen persist. The daemon reconnects to the display on restart.

**What if the developer changed display.py instead?** They restart the display, not the daemon: `lux display --restart` (or kill the display and let the daemon's `ensure_display()` re-spawn it on next `show()`). The daemon detects the broken Unix socket and reconnects via `_with_reconnect()`.

### Scenario 8: Display server crashes

**Precondition:** Daemon running, display running, proxies connected.

1. `lux display` crashes (segfault, OpenGL error, etc.).
2. The daemon's LuxClient holds a Unix socket that is now broken.
3. On the next `show()` call from any session:
   a. `_with_reconnect()` catches the `OSError`.
   b. Closes the stale socket.
   c. Calls `_get_client()` which calls `ensure_display()`.
   d. `ensure_display()` finds no PID file (or dead process). Spawns a new `lux display`.
   e. Waits for socket. Connects.
   f. Re-registers menu items via `_setup_apps()`.
   g. Retries the `show()` call. Succeeds.
4. From the proxy's perspective: one `show()` call took ~2s instead of ~50ms. No disconnect, no error.
5. Scenes are lost (they were in the crashed display's memory). The agent must re-send them.

**What notices:** The daemon, on the next tool call. No external monitor is needed.

**What restarts it:** `ensure_display()` inside the daemon, triggered by the tool call failure. Same mechanism as today.


## install.sh Changes

The Lux `install.sh` follows Quarry's `install.sh` structure. Key steps:

```
Step 1: Install punt-lux (uv tool install)
Step 2: Install mcp-proxy (if not present)
Step 3: Register daemon service (lux install)
Step 4: Health-check daemon
Step 5: Write proxy config (lux setup-proxy)
Step 6: Register marketplace
Step 7: Install plugin
```

Step 3 calls `lux install`, which is the Lux equivalent of `quarry install`:
- Writes launchd plist / systemd unit
- Loads/enables the service
- The daemon starts via the service manager

Step 5 calls `lux setup-proxy`, which writes `~/.punt-labs/mcp-proxy/lux.toml`:
```toml
[lux]
url = "ws://127.0.0.1:8430/mcp"
```

This is Quarry's `quarry login localhost` equivalent, but simpler: no TLS, no API key, just the WebSocket URL. The `write_proxy_config()` function in `remote.py` handles atomic write + chmod 0600.


## Migration Plan

### Existing users (have install.sh already run, direct stdio mode)

The migration is handled by re-running `install.sh`:

1. User runs updated `install.sh`.
2. `uv tool install punt-lux` upgrades the `lux` binary.
3. `install.sh` installs mcp-proxy (if not already present from Quarry).
4. `install.sh` runs `lux install` -- registers and starts the daemon service.
5. `install.sh` runs `lux setup-proxy` -- writes `lux.toml`.
6. `install.sh` reinstalls the plugin (new plugin.json with the `sh -c` wrapper).
7. Next Claude Code restart: plugin picks up the new plugin.json, detects mcp-proxy + lux.toml, uses proxy mode.

**Zero-downtime:** If the user does NOT re-run `install.sh`, the old plugin.json still works: `exec lux serve` (direct stdio). The fallback in the new plugin.json also preserves this: if lux.toml doesn't exist, it falls back to direct mode. Migration is opt-in via `install.sh`, not forced.

**Rollback:** If the daemon has issues, the user can:
1. `lux uninstall` -- removes the launchd/systemd service.
2. `rm ~/.punt-labs/mcp-proxy/lux.toml` -- removes proxy config.
3. Next Claude Code restart: plugin.json falls back to direct `lux serve`.

### Plugin marketplace users (automatic plugin updates)

When the marketplace plugin.json updates, users get the new `sh -c` wrapper automatically. But without `lux.toml`, it falls back to direct mode. They must run `install.sh` to get daemon + proxy mode.

This is the correct behavior: the proxy architecture requires service installation (launchd/systemd). That cannot be done silently via a plugin update.


## Alternatives Considered

### Alternative A: TCP transport in LuxClient

Build a TCP socket transport directly into `LuxClient` and `lux display`.

**Rejected:** Solves only Problem 3 (remote display). Does not address dev restarts (Problem 1) or session duplication (Problem 2). Also modifies the display server, which is the most sensitive component.

### Alternative B: Hot-reload in the display server

Watch source files for changes, exec-replace the display process.

**Rejected:** Solves only Problem 1, partially. ImGui context, OpenGL state, and window position are lost on exec-replace. Does not address Problems 2 or 3.

### Alternative C: ensure-daemon in plugin.json

The v1 proposal had `lux ensure-daemon && exec mcp-proxy --config lux` in the plugin.json one-liner. This auto-starts the daemon from the Claude Code launch path.

**Rejected in v2:** The daemon should be managed by launchd/systemd, not by a shell one-liner in plugin.json. Reasons:
- `KeepAlive=true` in launchd restarts the daemon on crash. A shell one-liner cannot do this.
- `RunAtLoad=true` starts the daemon at login. The proxy connects to an already-running daemon with zero startup delay.
- Quarry uses the service model (`quarry/service.py`). Lux should follow the same pattern for consistency.
- If the daemon is not running and the plugin.json one-liner cannot start it (e.g., permissions, port conflict), the MCP server fails silently. With a service, the failure is visible in `launchctl list` / `systemctl status`.

### Alternative D: No proxy, document the restart requirement

Accept the status quo.

**Rejected:** 30-60 second iteration cost per code change. 10-30 minutes lost per development session. Problems 2 and 3 remain unsolved. Every other Punt Labs MCP project is adopting mcp-proxy.


## Resolved Open Questions

1. **FastMCP WebSocket transport.** FastMCP (as of v3.2.0) supports `streamable-http` transport but does not natively expose a per-session WebSocket transport suitable for mcp-proxy's connection model. The daemon requires a custom Starlette/uvicorn ASGI app following Quarry's `http_server.py` pattern: Starlette routes `/mcp` (WebSocket) and `/health` (HTTP), with `_mcp_websocket_route()` extracting `session_key` and running an isolated MCP session per connection. This is ~250 lines, not 80. The Quarry implementation is the proven template.

2. **Port collision detection.** The current design fails hard on port collision (daemon exits with error). An alternative is to try a small range (8430-8439) and write the actual port to the port file. The proxy reads the port file instead of the TOML. This adds complexity (the TOML needs updating too). Recommendation: fail hard, document `$LUX_SERVE_PORT` override.

3. **Graceful daemon shutdown.** When the user shuts down their machine, `launchd` sends SIGTERM. The daemon should close WebSocket connections cleanly (so proxies reconnect rather than hang), write any pending state, and exit. The display is independent and stays running until its own window closes.


## Implementation Plan

**Phase 1: Daemon infrastructure** (service.py, daemon.py, remote.py, CLI additions)
- `lux serve --daemon`: WebSocket server with `/mcp` and `/health`
- `lux install` / `lux uninstall`: launchd/systemd service management
- `lux ensure-daemon`: health check + optional `--restart`
- `lux setup-proxy`: write `lux.toml`
- `lux daemon-status`: show PID, port, uptime, connected sessions

**Phase 2: Session multiplexing** (server.py refactor)
- Extract `_client`, `_client_lock`, session state into a class
- Add `_session_key` ContextVar
- Per-session event queues for `recv()`
- Per-session menu registration tracking with disconnect cleanup
- `run_mcp_session()` entry point for daemon.py

**Phase 3: Plugin migration** (plugin.json, install.sh)
- Update plugin.json with `sh -c` wrapper + fallback
- Update install.sh with daemon service + proxy config steps
- Verify: fresh install, existing install, no-proxy fallback

**Phase 4: Remote display** (documentation + testing)
- SSH tunnel setup guide
- `lux setup-proxy --url <ws-url>` for manual remote config
- Test: Host A daemon, Host B proxy, tunnel lifecycle
