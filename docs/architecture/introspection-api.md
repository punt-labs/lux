# Design: Lux Introspection and Control API

**Author:** Alan T (adt)
**Date:** 2026-05-12
**Status:** PROPOSED — target state. **Supersedes** `oo-refactoring-plan.md` Step 4.1 (which proposed removing `inspect_scene` / `list_scenes` / `screenshot`).
**Current state:** the three legacy ops still exist as ad-hoc methods in `display_client.py`. The generic pattern in §1 below is not yet implemented.

## Problem

Agents need to see inside the display server and modify its state at
runtime. Today we have three introspection operations (`inspect_scene`,
`list_scenes`, `screenshot`) built ad hoc. Adding a fourth requires
touching four files with no template. The API surface will grow to
15+ operations. Without a consistent pattern, each reinvents its
plumbing. This document defines the pattern, inventories every
operation, classifies each by security tier, resolves the wire
format, and provides a copy-paste implementation template.

## Definitions

- **Introspection**: A read-only query against display server state.
  Does not modify what the user sees.
- **Control**: A write operation that changes display server state.
  Modifies what the user sees.
- **Operation**: One introspection or control action. Has exactly one
  request, one response, one client method, and one MCP tool.
- **Security tier**: A risk classification (1/2/3) that determines
  whether an operation is safe by default or requires explicit opt-in.

## 1. The API Pattern

Every introspection/control operation follows the same four-layer
stack. No exceptions.

```text
MCP tool (tools/tools.py)
  -> Client method (display_client.py)
    -> Protocol message (protocol/messages/introspect.py)
      -> Display handler (display/server.py)
        -> Protocol response (protocol/messages/introspect.py)
      <- Client response queue (display_client.py)
    <- Formatted string (tools/tools.py)
```

### Naming convention

Given an operation named `get_display_info`:

| Layer | Name | Pattern |
|-------|------|---------|
| Protocol request | `QueryRequest` | Generic envelope (see section 4) |
| Protocol response | `QueryResponse` | Generic envelope |
| Display handler | `_handle_query` | Generic dispatcher |
| Client method | `query("get_display_info")` | Generic method |
| MCP tool | `get_display_info()` | `snake_case`, matches the operation name |

The MCP tool name is the user-facing identity. Everything below it is
generic plumbing that routes by a `method` string.

### Invariants

1. Every operation has exactly one MCP tool, one client call, one
   protocol round-trip.
2. Read operations return JSON. Write operations return a confirmation
   string or error.
3. Every operation checks `is_display_running()` before connecting.
4. Every operation uses `_with_reconnect()` for transient failures.
5. Every response includes an optional `error` field. Absence means
   success.

## 2. Operation Inventory

### Scenes domain

| Operation | MCP tool | R/W | Tier | Status |
|-----------|----------|-----|------|--------|
| Inspect scene element tree | `inspect_scene` | R | 2 | DONE |
| List scenes and frames | `list_scenes` | R | 1 | DONE |

### Screenshot domain

| Operation | MCP tool | R/W | Tier | Status |
|-----------|----------|-----|------|--------|
| Capture framebuffer as PNG | `screenshot` | R | 2 | DONE |

### Display domain

| Operation | MCP tool | R/W | Tier | Status |
|-----------|----------|-----|------|--------|
| Read display metadata | `get_display_info` | R | 1 | PLANNED |
| Read window settings | `get_window_settings` | R | 1 | PLANNED |
| Modify window settings | `set_window_settings` | W | 3 | PLANNED |
| Read current theme | `get_theme` | R | 1 | PLANNED |
| Set theme | `set_theme` | W | 3 | EXISTS (non-introspect path) |

`get_display_info` returns: renderer backend name, window resolution,
framebuffer scale factor (Retina), measured FPS, process uptime in
seconds, PID, protocol version.

`get_window_settings` returns: opacity (0.0--1.0), font\_scale,
decorated (bool), FPS target.

`set_window_settings` accepts any subset of: opacity, font\_scale,
decorated, fps\_target. Omitted fields are unchanged.

### Clients domain

| Operation | MCP tool | R/W | Tier | Status |
|-----------|----------|-----|------|--------|
| List connected clients | `list_clients` | R | 1 | PLANNED |

Returns per client: connection ID (sequential integer, not the OS
file descriptor), display name (from `ConnectMessage`), connection
time, menu registration count.

Future operations (not designed here): `kick_client`,
`rename_client`.

### Frames domain

| Operation | MCP tool | R/W | Tier | Status |
|-----------|----------|-----|------|--------|
| Read frame state | `get_frame_state` | R | 1 | PLANNED |
| Modify frame state | `set_frame_state` | W | 3 | PLANNED |

`get_frame_state(frame_id)` returns: position, size, minimized,
collapsed, focused, layout mode, scene list.

`set_frame_state(frame_id, ...)` accepts any subset of: minimized,
collapsed, focused. Position and size are future (requires GLFW
per-frame window tracking).

### Menus domain

| Operation | MCP tool | R/W | Tier | Status |
|-----------|----------|-----|------|--------|
| List all menus | `list_menus` | R | 1 | PLANNED |

Returns the Lux menu, Applications menu, Tools menu, and all
agent-registered menus with their items. Each item includes: label,
id, shortcut, enabled, owning client connection ID.

### Events domain

| Operation | MCP tool | R/W | Tier | Status |
|-----------|----------|-----|------|--------|
| Read recent events | `list_recent_events` | R | 1 | PLANNED |

Returns the last N interaction events (default 50, max 200). Each
event includes: element\_id, action, timestamp, value. This is a
ring buffer read, not a subscription.

### Errors domain

| Operation | MCP tool | R/W | Tier | Status |
|-----------|----------|-----|------|--------|
| Read recent errors | `list_errors` | R | 1 | PLANNED |

Returns the last N display-side errors/warnings (default 20, max
100). Each entry: timestamp, severity, message, context. The display
server already logs these; this operation exposes the tail of the
log buffer over the protocol.

### Summary counts

- Total operations: 14
- Already shipped: 3 (inspect\_scene, list\_scenes, screenshot)
- Existing but non-introspect: 1 (set\_theme via ThemeMessage)
- New to implement: 10
- Read operations: 10
- Write operations: 4

## 3. Security Tiers

| Tier | Name | Risk | What it includes |
|------|------|------|-----------------|
| 1 | `structure` | Low | Element kinds, IDs, counts, frame layout, client list, menu structure, display metadata. No data content. |
| 2 | `data` | Medium | Full element content (table rows, text bodies), screenshots, event payloads. Exposes user data. |
| 3 | `control` | High | Modify settings, move frames, change theme, clear scenes. Changes what the user sees. |

### Classification

| Tier | Operations |
|------|-----------|
| 1 | `list_scenes`, `get_display_info`, `get_window_settings`, `get_theme`, `list_clients`, `get_frame_state`, `list_menus`, `list_errors`, `list_recent_events` |
| 2 | `inspect_scene`, `screenshot` |
| 3 | `set_window_settings`, `set_frame_state`, `set_theme` |

The classification rule: if the response contains user-authored
content (table data, text, pixel data), it is tier 2. If it only
contains structural metadata (counts, IDs, settings), it is tier 1.
If it modifies state, it is tier 3. No operation is ambiguous under
this rule.

### Enforcement

Tier enforcement is a `luxd` concern (the policy layer), not a
`lux-display` concern (the renderer). Today, all operations are
permitted. When `luxd` ships, it will gate tier 2 and tier 3
operations behind session policy. `lux-display` always processes
any well-formed request -- it is a shared canvas with no access
control.

## 4. Protocol Design

### Decision: generic dispatcher (Option B)

**Option A** (status quo): one request/response dataclass pair per
operation. We have 3 today (`IntrospectRequest`/`Response`,
`ListScenesRequest`/`Response`, `ScreenshotRequest`/`Response`).
Adding 10 more means 20 new dataclasses, 20 serializers, 20
deserializers, and 20 branches in `message_from_dict`.

**Option B**: a generic `QueryRequest` with a `method` string and
`params` dict, returning a generic `QueryResponse` with a `result`
dict. The display dispatches on `method`. Adding a new operation
means adding one handler function and one MCP tool -- no protocol
changes.

Option B wins. The type safety loss is minimal: the MCP tool layer
already works with untyped JSON dicts, and the display handler
validates params at the point of use. The wire format gains
extensibility without protocol version bumps.

### Wire format

Request (client to display):

```json
{
  "type": "query_request",
  "method": "get_display_info",
  "params": {}
}
```

Response (display to client):

```json
{
  "type": "query_response",
  "method": "get_display_info",
  "result": { "backend": "opengl3", "fps": 60.1, "pid": 12345 },
  "error": null
}
```

### Protocol dataclasses

```python
@dataclass
class QueryRequest:
    """Generic introspection/control request."""
    method: str
    params: dict[str, Any] = field(default_factory=dict)
    type: Literal["query_request"] = "query_request"

@dataclass
class QueryResponse:
    """Generic introspection/control response."""
    method: str
    result: dict[str, Any] = field(default_factory=dict)
    type: Literal["query_response"] = "query_response"
    error: str | None = None
```

### Backward compatibility

The three existing specific message types (`introspect_request`,
`list_scenes_request`, `screenshot_request`) remain in the protocol
and continue to work. `message_from_dict` routes them to their
existing dataclasses. New operations use `query_request`/
`query_response` exclusively.

Migration path: when a client sends `query_request` with
`method="inspect_scene"`, the display handler calls the same
`_handle_introspect` logic and returns a `QueryResponse`. The old
`IntrospectRequest` path also works. Both coexist indefinitely --
removing the old types is a future breaking change we do not need
to make.

The display handler dispatches generically:

```python
_QUERY_HANDLERS: dict[str, Callable] = {
    "get_display_info": _handle_get_display_info,
    "get_window_settings": _handle_get_window_settings,
    "set_window_settings": _handle_set_window_settings,
    # ... one entry per operation
}
```

## 5. Implementation Template

Example: adding `get_theme`. After the one-time generic
infrastructure (PR 1), each new operation touches two files.

**`display/server.py`** -- add handler, register it:

```python
def _handle_get_theme(self, **_kwargs: Any) -> dict[str, Any]:
    current = getattr(self, "_current_theme", "dark")
    return {"current": current, "available": [str(t) for t in self._themes]}

# in __init__:
self._query_handlers["get_theme"] = self._handle_get_theme
```

**`display/server.py`** -- generic dispatcher (added once in PR 1):

```python
def _handle_query(self, sock: socket.socket, msg: QueryRequest) -> None:
    handler = self._query_handlers.get(msg.method)
    if handler is None:
        resp = QueryResponse(method=msg.method, error=f"Unknown method: {msg.method}")
    else:
        try:
            result = handler(**(msg.params or {}))
            resp = QueryResponse(method=msg.method, result=result)
        except Exception as exc:
            resp = QueryResponse(method=msg.method, error=str(exc))
    self._send_to_client(sock, resp)
```

**display_client.py** -- generic `query()` method (added once in PR 1):

```python
def query(self, method: str, params: dict[str, Any] | None = None) -> QueryResponse | None:
    self._send(QueryRequest(method=method, params=params or {}))
    # Same deadline/queue pattern as inspect_scene, list_scenes, screenshot
```

Add `_query_queue` to `__init__`, route `QueryResponse` in the
listener. Both one-time changes.

**tools.py** -- add MCP tool:

```python
@mcp.tool()
def get_theme() -> str:
    """Return the current theme and available themes."""
    if not is_display_running(default_socket_path()):
        return "not running"
    def _call() -> str:
        client = _get_client()
        response = client.query("get_theme")
        if response is None:
            return "timeout"
        if response.error:
            return f"error: {response.error}"
        return json.dumps(response.result, indent=2)
    return _with_reconnect(_call)
```

**Tests** -- round-trip in test\_protocol/ package, integration in
test\_tools.py (send `QueryRequest`, verify `QueryResponse` shape).

### Checklist for new operations

After PR 1, each new operation requires:

1. One handler method in `display/server.py`
2. One line in `_query_handlers`
3. One MCP tool function in `tools.py`
4. One integration test

No changes to protocol/ package, display_client.py, or message serialization.

## 6. Backward Compatibility

The three shipped operations (`introspect_request`,
`list_scenes_request`, `screenshot_request`) keep their dedicated
message types. `message_from_dict` routes them unchanged. Their MCP
tools continue to use dedicated client methods. New operations use
`query_request`/`query_response` exclusively.

Old-style and new-style messages coexist on the wire indefinitely.
No migration required for existing clients.

`set_theme` currently sends a fire-and-forget `ThemeMessage`. The
new query-based `set_theme` wraps the same logic but returns a
`QueryResponse` with error reporting. After the query-based path
ships, `tools.py`'s `set_theme` MCP tool switches to the query
path (gets error reporting). The `ThemeMessage` path remains in
the `protocol/` package and `display/server.py` for direct clients that may use it,
but `tools.py` no longer sends it.

## Implementation Order

1. **Generic infrastructure** (one PR): `QueryRequest`/
   `QueryResponse` in protocol/ package, generic `_handle_query` in
   display/server.py, `query()` method and `_query_queue` in display_client.py.
2. **Tier 1 reads** (one PR): `get_display_info`,
   `get_window_settings`, `get_theme`, `list_clients`,
   `list_menus`, `list_errors`, `list_recent_events`.
   (`list_recent_events` requires a ring buffer for events in
   display/server.py.)
3. **Tier 3 writes** (one PR): `set_window_settings`,
   `set_frame_state`. (`set_theme` migrates to query path.)
4. **Frame introspection** (one PR): `get_frame_state`. (Depends on
   GLFW window state tracking.)

Each PR is independently shippable. No PR depends on a later one.
