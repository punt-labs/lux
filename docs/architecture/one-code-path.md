# One Code Path — Typed Hub Operations, a REST Front Door, Thin Adapters

**Status:** design for the front-of-house rewrite. Read
[target.md](target/target.md) first; on any conflict that document wins.

## What This Design Decides

The engine core is done. `HubDisplay` holds authoritative UI state, and one
background replicator is the sole writer to the display. What is left is the
front of house — the surfaces a caller reaches the Hub through — and today the
front of house has three separate code paths for the same work.

1. The MCP tools hold the logic. `tools.py` is 795 lines across 23 tools; the
   scene-writing, validation, and layout rules live inside the tool bodies, not
   in a reusable layer.
2. The `lux show beads` command writes the display socket directly. It builds a
   scene and hands it to a `DisplayClient`, bypassing the Hub that is supposed
   to be authoritative.
3. The introspection tools reach around the Hub to query the display. A tool
   asks the display process what it is rendering instead of asking the Hub what
   is authoritative.

This design collapses those three paths into one. Every capability becomes a
single typed operation on the Hub. A typed REST API is the front door for the
command-line tool and for everything that is not an MCP agent. The MCP tools
become adapters with no logic of their own — they exist only because Claude
Code speaks MCP. The display's Unix socket becomes plumbing that only luxd
touches.

The design also moves luxd's MCP leg off the deprecated WebSocket transport
onto streamable HTTP, and evaluates letting Claude Code connect to luxd
directly so that mcp-proxy leaves lux's path.

## The Four Invariants and How Each Lands

The architecture standard fixes four invariants for every Punt Labs tool. This
design exists to make lux satisfy all four at the front of house.

**One engine, never duplicated per surface.** The engine is decomposed into the
Hub, which owns authority and dispatch, and the Display, which owns rendering.
This design adds one more internal part: an operations layer that is the single
home of every capability's logic. No capability is implemented twice. The tool
body, the REST route, and the command-line command all call the same operation.

**Every surface is a thin client.** After this change the MCP tools parse
arguments and format results; the REST routes bind a request body and return a
result; the command-line tool is an HTTP client of the REST API; the library
import surface is the operations layer itself. None of them reimplements the
engine.

**One code path.** `show` entered from an MCP agent, `show` entered from the
REST API, and `show` entered from `lux show beads` all run the identical
`render` operation. The capability runs the same engine-side code regardless of
which surface it entered from.

**Client-specific state lives in the engine, keyed by client.** The connection
scope, the topic subscriptions, the owned scenes, and the repository-scoped
display-mode config are all held by the Hub and keyed by the caller. A client
carries only its own identity and the working directory it alone can originate.

## The Operations Layer

The operations layer is the engine's front-of-house. It is a set of small
classes, grouped by concern, whose methods are the capabilities. Each method
takes a typed request and returns a typed result. It is the only place that
knows how a capability is carried out.

Every method does one of three things with the display-owned state it needs. It
reads or writes Hub-authoritative state directly. Or it proxies a read or write
to the display over luxd's own connection — the same single connection the
replicator already uses. In both cases the caller reaches the capability the
same way: through an operation on the Hub. Nothing outside luxd touches the
display socket.

### The complete operation inventory

The 27 tools that exist today map onto the operations below. Nothing is
dropped and nothing is invented; the mapping is one operation per capability,
with the two convenience operations (`render_table`, `render_dashboard`)
composing an element tree and delegating to the one `render` operation.

| Today's tool | Operation | State model |
|---|---|---|
| `show` | `render` | Hub-owned (`HubDisplay`) |
| `show_table` | `render_table` (composes the tree, delegates to `render`) | Hub-owned |
| `show_dashboard` | `render_dashboard` (composes the tree, delegates to `render`) | Hub-owned |
| `update` | `update` | Hub-owned |
| `clear` | `clear` | Hub-owned |
| `set_menu` | `set_menu` | Hub-owned (menu registry) |
| `register_tool` | `register_menu_item` | Hub-owned (menu registry) |
| `list_menus` | `list_menus` | Hub-owned (menu registry) |
| `inspect_scene` | `inspect_scene` | Hub-owned; optional display-mirror check proxied |
| `list_scenes` | `list_scenes` | Hub-owned (`HubDisplay`) |
| `list_clients` | `list_clients` | Hub-owned (session registry) |
| `subscribe` | `subscribe` | Hub-owned (pub-sub scope) |
| `unsubscribe` | `unsubscribe` | Hub-owned (pub-sub scope) |
| `publish` | `publish` | Hub-owned (pub-sub scope) |
| `recv` | `receive` | Hub-owned (session inbox) |
| `display_mode` | `read_display_mode` | Repo file (`<repo>/.punt-labs/lux.md`) |
| `set_display_mode` | `write_display_mode` | Repo file |
| `list_recent_events` | `list_recent_events` | Display-owned; proxied |
| `list_errors` | `list_errors` | Display-owned; proxied |
| `get_display_info` | `get_display_info` | Display-owned; proxied |
| `get_theme` | `get_theme` | Display-owned; proxied |
| `set_theme` | `set_theme` | Display-owned; proxied |
| `get_window_settings` | `get_window_settings` | Display-owned; proxied |
| `set_window_settings` | `set_window_settings` | Display-owned; proxied |
| `set_frame_state` | `set_frame_state` | Display-owned; proxied |
| `screenshot` | `screenshot` | Display-owned; proxied |
| `ping` | `ping` | Display liveness; proxied |

Three of the mappings are more than a rename, and each is a real correction the
one-code-path move exposes. They are explained under the query surface below.

### Module decomposition

The operations layer must not become a second 795-line god module. It is split
by concern, each module holding one operations class and staying within the
300-line, three-class budget.

```text
punt_lux/operations/
  __init__.py            # __all__ re-exports the operations facade
  scenes.py              # SceneOperations: render, update, clear
  conveniences.py        # ConvenienceOperations: render_table,
                         #   render_dashboard (compose a tree, delegate to render)
  queries.py             # QueryOperations: inspect_scene, list_scenes,
                         #   list_clients, list_recent_events, list_errors
  menus.py               # MenuOperations: set_menu, register_menu_item,
                         #   list_menus
  display_control.py     # DisplayControlOperations: get/set theme,
                         #   get/set window settings, get_display_info,
                         #   set_frame_state, screenshot, ping
  config.py              # DisplayModeOperations: read/write display mode
  pubsub.py              # PubSubOperations: subscribe, unsubscribe,
                         #   publish, receive
  models/                # Pydantic request and result models, split by concern
    __init__.py
    common.py            # OpError, the shared discriminated-error type
    scenes.py            # RenderRequest, SceneShown, ...
    queries.py           # SceneList, SceneInspection, ClientList, ...
    display.py           # DisplayInfo, ThemeState, WindowSettings, ...
    pubsub.py            # Subscribed, Published, Received, ...
```

An `Operations` facade in `__init__.py` composes the concern classes so a
single caller — an MCP adapter, a REST route, or a test — has one object to
call. Each concern class receives the Hub collaborators it needs (the
`HubDisplay`, the replicator, the session registry, the display connection) at
construction, so the classes stay testable without the full process.

### The error contract

Today the tools return magic strings: `"shown:<id>"`, `"not running"`,
`"timeout"`, `"error: scene not rendered — <reason>"`. A caller has to parse
prose to learn what happened. That is the type system giving up.

Every operation returns a discriminated result instead. A result is either the
operation's own success type, tagged `kind="ok"`, or the shared error type,
tagged `kind="error"`. Pydantic discriminates on the tag, so a caller pattern-
matches on a field rather than parsing a sentence, and an illegal
"success-with-an-error-message" value cannot be constructed.

```python
from typing import Annotated, Literal
from pydantic import BaseModel, Field

class OpError(BaseModel):
    kind: Literal["error"] = "error"
    code: Literal[
        "display_unavailable",  # the display process is not running
        "timeout",              # a proxied round-trip exceeded its bound
        "rejected",             # the Hub refused a malformed or invalid write
        "invalid_request",      # the request itself did not type-check
        "not_found",            # the named scene or resource does not exist
    ]
    reason: str
```

The `code` is a closed set the caller can branch on; the `reason` is the human
sentence for logs and messages. The MCP adapters format `OpError` back into the
exact legacy strings so that agents see no behavior change, while REST and the
command-line tool consume the typed form.

### Validation is the operation's job, not the adapter's

A request model that validates on construction can raise, and a raise from an
adapter body would escape past the string contract an MCP agent depends on. So
no adapter constructs a validated request. Each request model carries a
never-raising builder, and the operation is the single point where a request is
validated.

```python
class RenderRequest(BaseModel):
    ...
    @classmethod
    def parse(cls, raw: Mapping[str, object]) -> "RenderRequest | OpError":
        """Validate raw arguments, or return an OpError instead of raising."""
        try:
            return cls.model_validate(raw)
        except ValidationError as exc:
            return OpError(code="invalid_request", reason=_first_error(exc))
```

The operation accepts the builder's result — a valid request or an `OpError` —
and passes an `OpError` straight through:

```python
def render(self, request: RenderRequest | OpError, *, scope: Scope) -> SceneShown | OpError:
    if isinstance(request, OpError):
        return request
    # trust the validated request from here on; do the work
    ...
```

The consequence is that every surface validates against one schema — the request
model — applied at the operation boundary. An MCP adapter builds a plain mapping
(which cannot raise), calls `parse`, and hands the result to the operation; a bad
`layout` becomes an `OpError` the adapter formats to the legacy `"error: …"`
string, never an exception. A REST route binds its body to the same model, so
FastAPI produces the idiomatic 422 for malformed input from that one schema. The
validation rules live in exactly one place; only their rendering — a string for
MCP, a 422 for REST — differs by surface.

## The Query Surface

The query operations are where the reach-around is removed. Each display-owned
item needed an explicit decision: is the operation backed by Hub-authoritative
state, or does it proxy a read to the display over luxd's connection? The rule
that settled each one is simple. State the agent submitted, or state the Hub is
the authority for, is Hub-owned. State that is a fact about the running display
process — its renderer, its window, its framebuffer, its own diagnostic ring
buffers — is proxied.

### Owned by the Hub

**`inspect_scene` and `list_scenes` read Hub-authoritative state.** This is the
core correction. Today these tools ask the *display* what it is rendering. But
the Hub is the authority, and asking the replica instead of the authority is
exactly the reach-around the design removes. After this change both read from
`HubDisplay`. `inspect_scene` reports the element structure, each element's
`render_path` (`"abc"` or `"legacy"`), and its `resolved_props`. The
`domain_mirror_present` field described in the introspection API — whether the
display-side mirror exists — is a display fact, so it is an optional
add-on the operation proxies only when asked, and it is never read as Hub
authority.

**`list_clients` reads the Hub session registry.** Today it asks the display
which clients are connected to the display socket. After the Hub took over,
the display has exactly one socket client: luxd. So the old answer is now
meaningless. The meaningful client list is the set of Hub sessions — the MCP
connections and their scopes — which the Hub already holds. The operation
returns those. This is a bug fix the one-code-path move surfaces.

**`list_menus`, `set_menu`, and `register_menu_item` use a Hub menu registry.**
Menus are UI the agent submits, and submitted UI is what the Hub owns. Moving
the menu registry to the Hub makes `set_menu` and `register_menu_item` plain
Hub writes that the replicator pushes to the display like any scene, and makes
`list_menus` a Hub-authoritative read with no reach-around. This is the one
proxied-versus-owned call that carries real scope, because it moves state across
the boundary and touches the replicator, so it lands as its own commit in the
query PR. Menus are Hub-owned for the same reason every other piece of
agent-submitted UI is: the Hub is the authority for UI state (target.md), and a
menu is UI the agent submitted, not a fact about the running display.

### Proxied to the display

The remaining query and control operations are facts about, or settings of, the
running display process. The Hub cannot own an ImGui theme, a window's opacity,
a GPU backend string, a framebuffer capture, or the display's own ring buffer
of render errors. These operations proxy a read or write to the display over
luxd's single connection. The caller still reaches them the same way — through
a Hub operation — so there is still one code path; the reach-around that is
removed is the MCP tool or the command-line tool talking to the display
directly.

The proxied set is: `list_recent_events`, `list_errors`, `get_display_info`,
`get_theme`, `set_theme`, `get_window_settings`, `set_window_settings`,
`set_frame_state`, `screenshot`, and `ping`. Frame *composition* (which frame a
scene shows into, its title, its layout) is Hub-owned through the scene
presentation; only the transient minimize/expand state that `set_frame_state`
toggles is a display fact, so that one operation proxies.

### The `get_display_info` schema defect

The `get_display_info` payload carries `backend`, `window_width`,
`window_height`, `fps`, `pid`, `uptime_seconds`, `protocol_version`, and
`element_kinds`. The MCP output schema for the tool rejects its own valid
payload because the hand-maintained schema drifted from what the display
actually returns.

The fix depends on which of two shapes the adapter returns, so the inventory
splits by return shape. The two sets are the reason the fix is stated per set,
not once.

The **structured-output tools** are the ones whose value to an agent is a typed
record: `get_display_info`, `get_window_settings`, `get_theme`, `list_scenes`,
`inspect_scene`, `list_clients`, `list_menus`, `list_recent_events`, and
`list_errors`. For these the adapter returns the result model itself, and the
MCP output schema is derived from that model rather than hand-written. Because
one Pydantic model is both the operation's result type and the source the output
schema is generated from, a payload the model accepts cannot be rejected by a
schema built from the model. `get_display_info` is fixed here: its schema stops
being a separate artifact that can drift and becomes a projection of
`DisplayInfo`.

The **string-return tools** are the ones whose contract is a short status line
agents already parse: `show`, `show_table`, `show_dashboard`, `update`, `clear`,
`set_menu`, `register_tool`, `set_theme`, `set_window_settings`,
`set_frame_state`, `ping`, `display_mode`, `set_display_mode`, `screenshot`, and
the four pub-sub tools. For these the adapter formats the discriminated result
into the existing string with a formatter, so there is no output schema to drift
in the first place, and the legacy string contract is preserved unchanged. The
defect cannot recur in this set because these tools never carried a structured
output schema.

```python
class DisplayInfo(BaseModel):
    kind: Literal["ok"] = "ok"
    backend: str            # e.g. "OpenGL3"
    window_width: int
    window_height: int
    fps: float
    pid: int
    uptime_seconds: float
    protocol_version: str
    element_kinds: int
```

### Query result models

```python
class SceneSummary(BaseModel):
    scene_id: str
    element_count: int
    frame_id: str | None    # None when the scene is not shown into a frame
    owner: str | None       # the owning connection id, None if unowned

class FrameSummary(BaseModel):
    frame_id: str
    title: str
    scene_count: int
    scene_ids: list[str]
    layout: Literal["tab", "stack"]

class SceneList(BaseModel):
    kind: Literal["ok"] = "ok"
    scenes: list[SceneSummary]
    frames: list[FrameSummary]

class InspectedElement(BaseModel):
    id: str
    kind: str
    render_path: Literal["abc", "legacy"]
    # Resolved element state including defaults. A wire-shaped map because the
    # element kinds are open and each fills its own props; narrowed per kind by
    # the element codec, not here (PY-TS-14 wire boundary).
    resolved_props: dict[str, object]
    children: list["InspectedElement"] = []

class SceneInspection(BaseModel):
    kind: Literal["ok"] = "ok"
    scene_id: str
    elements: list[InspectedElement]
    # A display-side mirror check; None when not requested. Never read as Hub
    # authority (introspection-api.md).
    domain_mirror_present: bool | None = None

class HubClient(BaseModel):
    connection_id: str
    connected_seconds: float
    subscribed_topics: list[str]
    owned_scenes: list[str]

class ClientList(BaseModel):
    kind: Literal["ok"] = "ok"
    clients: list[HubClient]

class InteractionEvent(BaseModel):
    element_id: str
    action: str             # open-ended interaction name (clicked, changed, …)
    value: object | None = None   # the new value for value-bearing widgets
    timestamp: float

class RecentEvents(BaseModel):
    kind: Literal["ok"] = "ok"
    events: list[InteractionEvent]
    total_buffered: int

class DisplayErrorEntry(BaseModel):
    timestamp: float
    severity: Literal["error", "warning", "info"]
    message: str
    context: str

class RecentErrors(BaseModel):
    kind: Literal["ok"] = "ok"
    errors: list[DisplayErrorEntry]
    total_buffered: int

class MenuAction(BaseModel):
    kind: Literal["action"] = "action"
    id: str
    label: str
    shortcut: str | None = None    # None when the item has no accelerator
    icon: str | None = None        # None when the item has no icon

class MenuSeparator(BaseModel):
    kind: Literal["separator"] = "separator"

# A menu entry is an action or a separator, never a half-formed action.
MenuEntry = Annotated[MenuAction | MenuSeparator, Field(discriminator="kind")]

class Menu(BaseModel):
    label: str
    items: list[MenuEntry]

class MenuList(BaseModel):
    kind: Literal["ok"] = "ok"
    menus: list[Menu]
```

A separator is a shape, not an action with a missing id. Today `set_menu`
carries a separator as the sentinel payload `{"label": "---"}` — a menu entry
with no id and a magic label — while an action carries `{"label": "Run", "id":
"run_btn"}`. Modelling the entry as `MenuAction` with an optional id would leave
the type unable to say which of the two an entry is, and would invite an action
with no id, which is not a real state. The discriminated `MenuEntry` makes each
shape explicit: the boundary codec maps the `"---"` sentinel to a
`MenuSeparator` and an id-bearing entry to a `MenuAction`, so the `"---"`
convention lives at the wire boundary and never in the typed model. This is why
`register_menu_item` takes a `MenuAction`, not a `MenuEntry`: registering a tool
always registers an action.

### Display-control and pub-sub result models

```python
ThemeName = Literal[
    "imgui_colors_light", "imgui_colors_dark", "imgui_colors_classic",
    "darcula", "darcula_darker", "material_flat", "photoshop_style",
    "grey_flat", "cherry", "light_rounded", "microsoft_style",
    "from_imgui_colors_dark",
]

class ThemeState(BaseModel):
    kind: Literal["ok"] = "ok"
    theme: ThemeName
    available: list[ThemeName]

class WindowSettings(BaseModel):
    kind: Literal["ok"] = "ok"
    opacity: float
    font_scale: float
    decorated: bool
    fps_idle: float

class Screenshot(BaseModel):
    kind: Literal["ok"] = "ok"
    path: str               # PNG file path on the display host

class Pong(BaseModel):
    kind: Literal["ok"] = "ok"
    rtt_seconds: float

class SetMenuRequest(BaseModel):
    menus: list[Menu]

class BusEvent(BaseModel):
    topic: str
    payload: dict[str, object]   # app-defined topic payload

class Subscribed(BaseModel):
    kind: Literal["ok"] = "ok"
    topic: str

class Unsubscribed(BaseModel):
    kind: Literal["ok"] = "ok"
    topic: str

class Received(BaseModel):
    kind: Literal["ok"] = "ok"
    event: BusEvent | None = None   # None is the documented "inbox empty" contract
```

## The REST Surface

luxd already runs a Starlette application on uvicorn with a `/health` route and
a `/mcp` WebSocket route. FastAPI is a subclass of Starlette, so the top-level
application becomes a FastAPI instance and the existing routes keep working.
The typed routes are added as FastAPI routers whose request bodies and
responses are the operations layer's Pydantic models. Each route binds the body
to a request model, calls one operation, and returns the result model. FastAPI
serializes the model and derives the OpenAPI schema from it, so there is no
second schema to maintain. This is the same shape as quarry's daemon, which is
FastAPI on uvicorn, and it reads as the same family.

The routes follow the resource they act on.

| Method and path | Operation | Request body | Result |
|---|---|---|---|
| `PUT /scenes/{scene_id}` | `render` | `RenderRequest` | `SceneShown \| OpError` |
| `PATCH /scenes/{scene_id}` | `update` | `UpdateRequest` | `SceneShown \| OpError` |
| `DELETE /scenes` | `clear` | — | `Cleared \| OpError` |
| `GET /scenes` | `list_scenes` | — | `SceneList` |
| `GET /scenes/{scene_id}` | `inspect_scene` | — | `SceneInspection \| OpError` |
| `GET /clients` | `list_clients` | — | `ClientList` |
| `GET /menus` | `list_menus` | — | `MenuList` |
| `PUT /menus` | `set_menu` | `SetMenuRequest` | `Ok \| OpError` |
| `POST /menus/items` | `register_menu_item` | `MenuAction` | `Ok \| OpError` |
| `GET /events` | `list_recent_events` | `count` query | `RecentEvents` |
| `GET /errors` | `list_errors` | `count` query | `RecentErrors` |
| `GET /display` | `get_display_info` | — | `DisplayInfo \| OpError` |
| `GET /display/theme` | `get_theme` | — | `ThemeState \| OpError` |
| `PUT /display/theme` | `set_theme` | `SetThemeRequest` | `ThemeState \| OpError` |
| `GET /display/window` | `get_window_settings` | — | `WindowSettings \| OpError` |
| `PATCH /display/window` | `set_window_settings` | `WindowSettingsPatch` | `WindowSettings \| OpError` |
| `PATCH /display/frames/{frame_id}` | `set_frame_state` | `FrameStatePatch` | `Ok \| OpError` |
| `GET /display/screenshot` | `screenshot` | — | `Screenshot \| OpError` |
| `GET /display/ping` | `ping` | — | `Pong \| OpError` |
| `GET /display-mode` | `read_display_mode` | `repo` query | `DisplayModeState \| OpError` |
| `PUT /display-mode` | `write_display_mode` | `DisplayModeRequest` | `DisplayModeState \| OpError` |
| `POST /topics/{topic}/publish` | `publish` | `PublishRequest` | `Published` |

A route does one thing beyond binding and calling: it maps the discriminated
result to an HTTP status through one shared table, so every route reports
failures the same way. `kind="ok"` returns 200. An `OpError` maps by its `code`:
`invalid_request` to 422, `not_found` to 404, `rejected` to 409,
`display_unavailable` to 503, and `timeout` to 504. FastAPI's own body-binding
produces the 422 for a malformed request before the operation runs, from the
same request model; the operation's semantic `OpError` values produce the rest.
The mapping is a table, not per-route logic, so a new operation inherits it for
free.

The scene, display-mode, and publish request models make the currently untyped
tool arguments precise.

```python
class FrameFlags(BaseModel):
    no_resize: bool = False
    no_collapse: bool = False
    auto_resize: bool = False
    no_title_bar: bool = False
    no_background: bool = False
    no_scrollbar: bool = False

class FrameSpec(BaseModel):
    frame_id: str | None = None
    frame_title: str | None = None
    size: tuple[int, int] | None = None    # None means let the display choose
    flags: FrameFlags | None = None
    layout: Literal["tab", "stack"] | None = None

class RenderRequest(BaseModel):
    scene_id: str
    # Wire element trees. dict-shaped because element kinds are open and each
    # self-validates via the element codec and the submission gate inside the
    # operation (PY-TS-14 wire boundary).
    elements: list[dict[str, object]]
    title: str | None = None
    layout: Literal["single", "rows", "columns", "grid"] = "single"
    frame: FrameSpec | None = None

class SceneShown(BaseModel):
    kind: Literal["ok"] = "ok"
    scene_id: str

class SetPatch(BaseModel):
    kind: Literal["set"] = "set"
    id: str
    # The fields to set on the element; wire-shaped because element props are
    # open and validated per kind by the element codec in the operation.
    set: dict[str, object]

class RemovePatch(BaseModel):
    kind: Literal["remove"] = "remove"
    id: str

# A patch sets fields on an element or removes it — never both, never neither.
ScenePatch = Annotated[SetPatch | RemovePatch, Field(discriminator="kind")]

class UpdateRequest(BaseModel):
    patches: list[ScenePatch]

class Cleared(BaseModel):
    kind: Literal["ok"] = "ok"

class Ok(BaseModel):
    kind: Literal["ok"] = "ok"

class SetThemeRequest(BaseModel):
    theme: ThemeName

class WindowSettingsPatch(BaseModel):
    opacity: float | None = None       # only provided fields change
    font_scale: float | None = None
    decorated: bool | None = None
    fps_idle: float | None = None

class FrameStatePatch(BaseModel):
    minimized: bool | None = None

class DisplayModeRequest(BaseModel):
    mode: Literal["on", "off"]
    repo: str                          # absolute path to the caller's project

class DisplayModeState(BaseModel):
    kind: Literal["ok"] = "ok"
    mode: Literal["on", "off"]

class PublishRequest(BaseModel):
    payload: dict[str, object] = {}    # app-defined topic payload

class Published(BaseModel):
    kind: Literal["ok"] = "ok"
    delivered: int
```

The `layout` and `frame.layout` fields are `Literal` types, so the
`match layout` and `match frame_layout` validation currently written by hand in
the `show` tool disappears — Pydantic rejects a bad value at bind time with a
precise error. The `frame_flags` argument, today a `dict[str, bool]` with six
known keys listed in a docstring, becomes the `FrameFlags` class.

### The health route and the transport policy

`/health` becomes a typed FastAPI route returning the model below rather than a
raw dict. It keeps reporting the hub status and session count.

```python
class HubHealth(BaseModel):
    status: Literal["ok"] = "ok"
    sessions: int
```

It stays a plain unauthenticated liveness probe, because a service manager and
`lux hub-status`
poll it. The transport policy — which callers luxd will serve — is resolved in
the transport section below and applies to every route on the app, health
included: luxd binds loopback, and a non-loopback bind is refused at startup
rather than accepted and then rejected per request.

### Pub-sub and REST

Publishing is a stateless fan-out, so it maps cleanly onto `POST /topics/
{topic}/publish`. Subscribing and receiving are not stateless: they register a
writer and queue an inbox against a live session, which is the MCP connection.
They do not fit a stateless REST call and the command-line tool has no need of
them. So `subscribe`, `unsubscribe`, and `receive` live in the operations layer
like everything else — one code path — but only the MCP surface exposes them,
because only the MCP surface has a caller for them. This follows the
architecture standard's guidance to build a surface where it has a caller and
keep it thin where it does not.

## The Adapter Contract

An MCP tool body, after this change, may contain three things and nothing else:
it may parse its arguments into a typed request, call exactly one operation, and
format the typed result into the tool's string return. It may hold no
validation, no scene construction, no layout rules, and no display round-trips.
Those all live in the operation.

The `show` tool is the worked example. Today its body validates the layout with
a `match`, validates the frame layout with a second `match`, checks the frame
size length, builds typed elements, runs the submission gate, installs into
`HubDisplay`, and marks the scene dirty — 60-odd lines of logic. After the
change it assembles its arguments into a plain mapping, hands them to the request
builder, and formats the result.

```python
@mcp.tool()
def show(
    scene_id: str,
    elements: list[dict[str, Any]],
    title: str | None = None,
    layout: str = "single",
    frame_id: str | None = None,
    frame_title: str | None = None,
    frame_size: list[int] | None = None,
    frame_flags: dict[str, bool] | None = None,
    frame_layout: str | None = None,
) -> str:
    request = RenderRequest.parse(
        {
            "scene_id": scene_id,
            "elements": elements,
            "title": title,
            "layout": layout,
            "frame": {
                "frame_id": frame_id,
                "frame_title": frame_title,
                "size": frame_size,
                "flags": frame_flags,
                "layout": frame_layout,
            },
        }
    )
    return _format_scene(OPERATIONS.render(request, scope=_scope()))
```

The body builds a plain dictionary and calls `RenderRequest.parse`, which never
raises. It constructs no validated object itself, so nothing it does can escape
past the string return. `_format_scene` maps `SceneShown` to `"shown:<id>"` and
both an `OpError` from validation and an `OpError` from the operation to
`"error: scene not rendered — <reason>"`, preserving the exact strings agents
already parse. The layout and frame-layout `match` blocks are gone: an invalid
`layout` fails inside `parse`, becomes an `invalid_request` `OpError`, and
`render` passes it straight through to `_format_scene`. The `_scope()` helper
resolves the caller's connection scope, which for an MCP tool is the session's
`ConnectionId`, as today.

### The convenience tools stay thin

`show_table` and `show_dashboard` build an element tree today, and the adapter
contract forbids exactly that in a tool body. So the tree-building moves into the
operations layer. Each convenience becomes a typed operation — `render_table`
and `render_dashboard` — that takes the convenience's own typed request (columns,
rows, filters, detail for the table; metrics, charts, table for the dashboard),
composes the element tree, and delegates to `render`. The MCP tool bodies then
look exactly like `show`: assemble arguments into a mapping, call the
convenience request builder, format the result. No tree construction in any tool
body.

The target architecture (DES-040) says these conveniences should eventually be
skills composed from `show`, not standing MCP tools, because the tool contract
every agent carries should not grow one entry per widget. This unit keeps them as
standing tools — removing tools is a separate, agent-facing change out of this
unit's scope — but it puts their logic where a skill would call it: a typed
convenience operation over `render`. When the skills move happens, the standing
tools are deleted and the skills call the same `render_table` and
`render_dashboard` operations, so no logic moves twice.

### The command-line tool on REST

`lux show beads` today constructs a `DisplayClient`, connects to the display
socket, and calls `show_async`. After this change it builds the same beads
element tree with the existing `BeadsBrowser` — which is already pure, no socket
in it — and sends it to luxd's REST API.

```python
@show_app.command("beads")
def beads(all_issues: bool = typer.Option(False, "--all", "-a")) -> None:
    browser = BeadsBrowser()
    issues, load_error = browser.load(all_issues=all_issues)
    elements = browser.build_elements((issues, load_error))
    project = Path.cwd().name or "unknown"

    client = LuxRestClient(port=HubPaths().read_port())
    result = client.render(
        RenderRequest(
            scene_id=f"beads-{project}",
            elements=[e.to_dict() for e in elements],
            title=f"Beads: {project}",
            frame=FrameSpec(frame_id=f"beads-{project}", frame_title=f"Beads: {project}"),
        )
    )
    typer.echo(_beads_message(result, issues, load_error))
```

`LuxRestClient` is a thin HTTP client — it reads luxd's port from `HubPaths`, as
`lux hub-status` already does, and posts the request model to the REST route. No
`DisplayClient`, no socket path, no down-check of the display. The Hub decides
whether the display is reachable and returns an `OpError` if it is not. After
this lands, `DisplayClient` is imported only by luxd's own Hub layer — the
replicator and the proxied query operations — and by nothing on any client
surface. The display socket has become Hub-internal plumbing.

## The Transport Leg

luxd's `/mcp` route today is a WebSocket endpoint built on
`mcp.server.websocket.websocket_server`, which the MCP SDK deprecated and
removes in its 2.0 release. That is why `pyproject.toml` pins `mcp>=1.28.1,<2`,
and why this unit is the prerequisite for ever lifting that pin.

### Streamable HTTP, mounted beside the REST routes

The MCP leg moves to streamable HTTP, the MCP SDK's current transport. FastMCP
serves streamable HTTP as an ASGI application, which mounts on the same FastAPI
app that hosts the REST routes and `/health`, on the same uvicorn server, at the
same `/mcp` path. biff already runs FastMCP over streamable HTTP for its daemon
mode, so this is a proven shape in the family; luxd adopts it. The result reads
like the rest of the family: quarry's daemon is FastAPI on uvicorn, and vox's
voxd is Starlette on uvicorn with a WebSocket control channel — luxd becomes a
FastAPI app on uvicorn with an MCP leg mounted beside its REST routes. The
deprecated WebSocket route and its `websocket_server` import are deleted, and the
`mcp<2` pin's reason disappears.

### Retiring mcp-proxy from lux's path

mcp-proxy exists to bridge Claude Code's stdio to luxd's WebSocket. Claude Code
can also connect to an HTTP MCP server directly, through its native HTTP MCP
configuration. Once luxd speaks streamable HTTP at
`http://127.0.0.1:8430/mcp`, Claude Code can point at that URL and the bridge is
no longer needed for lux. The recommendation is to retire mcp-proxy from lux's
path and connect Claude Code directly.

mcp-proxy's transport decision (its DES-001) chose WebSocket for three reasons,
and each is answered rather than dismissed.

Its first reason was that bidirectional server-to-client push is required, and
plain HTTP cannot deliver unsolicited messages. Streamable HTTP answers this: it
carries server-initiated messages on its SSE stream, which is exactly the push
channel WebSocket provided. lux's interaction events reach the agent over that
stream.

Its second reason was that WebSocket supplies message framing and keepalive that
a raw socket would force you to build. Streamable HTTP is HTTP: framing and
keepalive are the protocol's own, so the do-it-yourself concern that counted
against a raw Unix socket does not count against HTTP.

Its third reason was that quarry and biff already ran HTTP servers, so a
WebSocket upgrade endpoint added onto the same server for free. That is still
true, but streamable HTTP needs no upgrade endpoint at all — it is an ordinary
mounted ASGI app — which is simpler still. And the consumer landscape that made
shared WebSocket infrastructure attractive has changed. biff, the strongest push
rationale in DES-001, no longer runs a daemon; it is on NATS. quarry, vox, and
z-spec are on stdio. lux is the one remaining WebSocket consumer, and this unit
moves it off. The shared-infrastructure argument for WebSocket has no consumers
left to share.

Retiring mcp-proxy from lux's path does not delete the binary. Any other
consumer keeps it. The change is cross-repo and follows the breaking-change
procedure: message the mcp-proxy owner, agree the change, land lux's direct-HTTP
connection and its config, record the superseding ADR in mcp-proxy's own
decision log, and verify Claude Code reaching luxd end-to-end. The superseding
ADR text is in Appendix B.

### The bind-host and loopback policy

luxd binds `127.0.0.1` by default but accepts a `--host` argument. Today the
only handshake guard is an Origin check for cross-site hijacking; there is no
per-request loopback reject. So an operator who sets `--host 0.0.0.0` gets a
listener that binds the wider interface while the transport policy stays fixed to
loopback semantics — the bind and the policy disagree, and the mismatch is
silent rather than refused.

The resolution for this unit is to refuse a non-loopback `--host` at startup with
a clear message, so the bind and the policy can never disagree. Remote access
needs authentication that is not in this unit's scope — the multi-machine future
in target.md is real, but enabling an off-loopback bind without a bearer token
and a bind-derived origin policy would be a security regression. So luxd fails
fast, at startup, with an explanation: it binds loopback, and a non-loopback
bind stops the process at startup. When the multi-machine future is built, the
off-loopback bind arrives together with its authentication and an origin policy
derived from the bind host.

The streamable-HTTP move also relocates the cross-site protection. The WebSocket
path guarded against cross-site WebSocket hijacking with an Origin check.
Streamable HTTP guards against DNS-rebinding with host validation, which the MCP
SDK's streamable-HTTP server exposes as a setting; the loopback policy migrates
onto that. The log ordering is tidied in the same pass, scoped to the new
startup guard: the Origin check today already precedes the "connected" log and
returns before it, so an Origin rejection logs nothing spurious. The care is that
the added host-policy refusal must sit at startup, before any per-connection
"connected" log can run, so a refused bind never produces a connection log at
all.

## Proposed PR Decomposition

The epic sketched five PRs. The order below keeps that shape but folds the
"collapse the MCP tools to adapters" step into the two extraction PRs rather
than deferring it to a standalone PR. The reason is the refactoring protocol:
extracting an operation and leaving the tool still holding the logic would
create an operations layer with no callers — dead code — which the protocol
forbids. Every extraction wires its callers forward in the same PR. So the MCP
tools become adapters as their operations are extracted, and each PR leaves the
MCP string contract intact and pinned by tests. The standalone adapter PR
shrinks to the command-line and socket work that genuinely comes later.

Each PR is one rollback-coherent unit: if it broke, this is what reverts
together.

**PR A — the operations layer and the Hub-authoritative adapters.** Introduce
the `operations/` package and the Pydantic models. Extract `render`, `update`,
`clear`, the four pub-sub operations, and the two display-mode operations, and
rewire their MCP tools to thin adapters in the same PR. This is the largest PR
and the foundation; it lands the error contract and the model package. Rollback
unit: the operations layer plus the adapter rewrite for these tools. The lux
one-code-path ADR (Appendix A) lands here, where the decision first takes
structural form.

**PR B — the query operations and the reach-around removal.** Extract the query
and proxied-control operations. Move `inspect_scene`, `list_scenes`, and
`list_clients` onto Hub-authoritative reads; move the menu operations onto the
Hub menu registry; make the display-fact operations proxy over luxd's
connection. Rewire the introspection tools to adapters and fix the
`get_display_info` schema defect by making the typed model the single schema.
Rollback unit: the query operations plus the introspection adapter rewrite. This
is where the three corrections (scenes-from-Hub, clients-from-Hub, menus-owned)
land.

**PR C — the typed REST surface.** Turn luxd's Starlette app into a FastAPI app,
add the typed routers over the operations layer, and make `/health` a typed
route. This PR is additive: nothing depends on the REST surface yet, so it can
land and be exercised on its own. Rollback unit: the REST surface.

**PR D — the command-line tool onto REST, and the socket internalized.** Move
`lux show beads`, and the display-touching parts of `lux ping` and
`lux hub-status`, onto the REST API through a thin `LuxRestClient`. Delete the
command-line tool's direct `DisplayClient` use, so the display socket is
imported only by luxd's Hub layer. Rollback unit: the command-line transport
swap. Depends on PR C.

**PR E — streamable HTTP and the mcp-proxy retirement.** Replace the WebSocket
`/mcp` route with FastMCP streamable HTTP on the same app, resolve the
bind-host policy (refuse non-loopback at startup, migrate the origin guard onto
streamable-HTTP host validation, fix the log ordering), connect Claude Code
directly and retire mcp-proxy from lux's path via the cross-repo procedure, and
lift the `mcp<2` pin. Both transport ADRs land here — the lux ADR's transport
section takes effect and the mcp-proxy superseding ADR (Appendix B) is recorded
in that repo. Rollback unit: the transport swap and its configuration.

## Settled Decisions

Three calls that could have been forks are settled here, with the reasoning, so
the design leaves nothing open.

**Menu state is Hub-owned.** Every display-fact operation is proxied, but a menu
is not a display fact — it is UI the agent submitted, and the Hub is the
authority for submitted UI (target.md). Owning menu state makes `set_menu` and
`register_menu_item` plain Hub writes the replicator pushes, and `list_menus` a
Hub-authoritative read with no reach-around. It moves state across the boundary
and touches the replicator, so it lands as its own commit in the query PR to
keep the scope contained.

**REST uses one default scope for this unit.** An MCP call carries a
`ConnectionId` from its session, which scopes its owned scenes and
subscriptions; a REST call has no such session. This does not bite the local
single-user slice, which is already a single-connection slice today where
`clear` is global and scenes share one scope. REST therefore uses one default
Hub scope, matching that reality. Per-caller REST scoping arrives with the
multi-user future, when a REST call carries an explicit session identity — a
header or a field — and the same scoping the MCP leg already has.

**mcp-proxy retirement is sequenced, not shimmed.** The streamable-HTTP server
lands and Claude Code connecting directly is verified live before the shipped
plugin config switches from the proxy command to the direct HTTP URL. The proxy
path keeps working until the direct path is confirmed, then the config flips in
the following release. This is a one-time config change with no dual readers in
the code — sequencing, not a compatibility shim.

## Appendix A — lux DESIGN.md ADR (ready to land)

The following is written to append to lux's `DESIGN.md` as the next ADR.

---

### DES-055: One Code Path — Typed Hub Operations, a REST Front Door, Thin Adapters

**Status:** accepted.

**Context.** lux's engine core became Hub-authoritative: `HubDisplay` owns UI
state and one replicator is the sole display writer. The front of house did not
follow. Three separate code paths did the same work. The MCP tools held the
logic in a 795-line `tools.py`. `lux show beads` wrote the display socket
directly, bypassing the Hub. The introspection tools queried the display instead
of the Hub. This violated the architecture standard's four invariants at the
surface layer: logic was duplicated per surface, the surfaces were not thin
clients, a capability had more than one code path, and client state was read
from the wrong authority.

**Decision.** Every capability becomes one typed operation in a new
`operations/` layer, the single home of front-of-house logic. Each operation
takes a typed request and returns a discriminated result — the operation's
success type or a shared `OpError` — replacing the magic-string returns. A typed
FastAPI REST API on luxd's existing uvicorn app is the front door for the
command-line tool and every non-MCP caller. The MCP tools become adapters that
parse arguments, call one operation, and format the result; they hold no logic.
`lux show beads` calls the REST API instead of the display socket. Introspection
reads Hub-authoritative state: `inspect_scene` and `list_scenes` read
`HubDisplay`, `list_clients` reads the Hub session registry, and the menu
registry moves to the Hub. Display-process facts — theme, window, framebuffer,
diagnostic buffers — are reached through Hub operations that proxy to the display
over luxd's own connection, so the display socket becomes Hub-internal plumbing.
The `get_display_info` schema defect is fixed by making the typed model the
single schema. In the same unit, luxd's MCP leg moves off the deprecated
WebSocket transport onto streamable HTTP mounted beside the REST routes, and
Claude Code connects to luxd directly so mcp-proxy leaves lux's path; luxd
refuses a non-loopback bind at startup.

**Rejected: keep the WebSocket transport with a lux-owned adapter layer.** This
would add the operations layer and the REST surface but leave the MCP leg on the
deprecated `websocket_server`, keeping the `mcp<2` pin and mcp-proxy in the
path. It defers the transport debt without removing it, and it keeps two
transports (WebSocket for MCP, HTTP for REST) on one app when one transport
serves both. Rejected because the pin blocks every future MCP SDK upgrade and
the second transport is avoidable.

**Rejected: per-surface logic — let each surface keep its own implementation.**
This is the status quo generalized: the REST surface would reimplement what the
tools do rather than share an operation. It fails the one-engine and
one-code-path invariants directly, doubles the maintenance surface, and lets the
surfaces drift. Rejected because it is the exact problem this ADR removes.

**Rejected: move all display-owned state to Hub ownership.** Making the Hub own
the theme, window settings, framebuffer, and the display's diagnostic ring
buffers would force the display to replicate renderer-internal state upward for
no caller benefit, and the Hub cannot be the authority for a GPU backend string
or a live frame rate. Proxying those reads over luxd's one connection keeps a
single code path through the Hub without a meaningless ownership move. Menu
state is the deliberate exception, because menus are agent-submitted UI.

**Consequences.** One code path per capability, verified by the same operation
running under three surfaces. The MCP string contract is preserved by the
adapters, so agents see no change. The `mcp<2` pin is lifted. The command-line
tool and introspection stop reaching around the Hub. The multi-machine future
stays open but unbuilt: luxd is loopback-only until authentication is added.

---

## Appendix B — mcp-proxy DESIGN.md superseding ADR (ready to land)

The following is written to append to mcp-proxy's `DESIGN.md`. It supersedes
DES-001 in premise for lux and records why.

---

### DES-017: Streamable HTTP Supersedes WebSocket for lux; lux Leaves the Proxy Path

**Status:** accepted. **Supersedes:** DES-001 (in premise, for lux).

**Context.** DES-001 chose WebSocket for the proxy-to-daemon transport on three
grounds: bidirectional server push is required and HTTP cannot deliver it;
WebSocket supplies framing and keepalive a raw socket would not; and the daemons
already ran HTTP servers a WebSocket endpoint could add onto. Those grounds were
sound when every candidate daemon needed the proxy and HTTP had no push. The MCP
SDK has since shipped streamable HTTP, and the consumer landscape has changed.

**What changed in premise.** Streamable HTTP carries server-initiated messages
on its SSE stream, so the push that only WebSocket could give in DES-001 is now
available over HTTP — the first and load-bearing reason no longer holds. Framing
and keepalive are HTTP's own on the streamable-HTTP transport, so the second
reason does not apply. The third reason — shared HTTP servers make a WebSocket
upgrade cheap — is now moot for lux, because streamable HTTP needs no upgrade
endpoint; it is a mounted ASGI app. And the consumers changed: biff, the
strongest push case in DES-001, no longer runs a daemon and is on NATS; quarry,
vox, and z-spec are on stdio; lux is the last WebSocket consumer.

**Decision.** lux moves its MCP leg to streamable HTTP on luxd's existing
uvicorn app and lets Claude Code connect directly through its native HTTP MCP
configuration. mcp-proxy is retired from lux's path. The proxy binary is not
deleted — any remaining consumer keeps it — but lux no longer depends on it, and
the WebSocket transport is no longer lux's reason for the proxy to exist.

**Rejected: keep lux on WebSocket through the proxy.** This would hold the whole
family on the deprecated WebSocket server transport for one consumer's sake and
keep lux pinned below MCP SDK 2.0. Rejected: streamable HTTP gives lux push,
framing, and keepalive without the proxy, and the pin blocks every SDK upgrade.

**Consequences.** lux reaches luxd over streamable HTTP with no bridge. The
proxy's WebSocket rationale has no lux consumer left. Any future WebSocket
consumer must re-argue DES-001 on its own terms, because the shared-daemon
premise that justified it is gone.

---
