# Display-Local State Introspection (Hub-Mediated)

**Status:** design proposal — pending operator ratification. Not yet
implemented. Bead `lux-221j`.

I read `docs/architecture/target/target.md` (including the DES-088
content/visibility split and the `WidgetStateStore`/`SceneReplica`
sections), `docs/architecture/target/introspection-api.md`,
`docs/architecture/target/ui-model.md`, and
`docs/architecture/target/topology.md` before writing this. Where this
document and `target.md` would ever disagree, `target.md` governs; I have
not found a disagreement — this proposal is an extension of the read-only
introspection surface `target.md` already calls for, not a change to the
authority model.

## Problem

Two verification gaps, both closed the same way — a bounded, read-only,
Hub-mediated proxy to the running Display, following the shape
`DisplayFactProxy` and `FrameVisibilityProxy` already established:

1. **Display-local widget/visibility state is unobservable.** An agent can
   read the Hub's authoritative tree (`inspect_scene`) and the Hub's
   session roster (`list_clients`), but cannot see what the Display is
   actually holding in its own `WidgetStateStore` (selection, scroll,
   in-progress text) or in the parts of `Frame` that DES-088 declares
   Display-owned and deliberately never replicated back — `active_tab`
   and `cascade_index` today join `visibility`, which is already proxied.
   Without this, an agent cannot prove the Hub and the Display agree, and
   cannot run-and-prove a class of lifecycle fixes that live entirely on
   the Display side.
2. **Hub-side per-connection lifecycle state is unobservable.**
   `list_clients` already reports `subscribed_topics` and `owned_scenes`
   per session (`operations/models/query_clients.py:15-27`), but not
   whether the connection currently has a writer bound
   (`Hub.has_writer`, `domain/hub/hub.py:81-83`) or how deep its inbox
   queue is (`domain/hub/inbox.py`'s per-connection `SimpleQueue`). Both
   are exactly what is needed to run and prove the lease-reap cascade
   convergence (`lux-vvmt`) and the twin-subscription-loss defect
   (`lux-95zt`): a reap that silently leaves a stale writer bound, or a
   publish that piles up in a queue nobody drains, is invisible today.

## Non-Goals

- This does not make the Display authoritative for anything. Every value
  this design exposes is read-only, proxied, and never installed as Hub
  state — the same rule `DisplayFactProxy` and `FrameVisibilityProxy`
  already hold for painted geometry and frame visibility
  (`operations/display_facts.py:1-12`, `operations/frame_visibility_proxy.py:1-8`).
- This does not compute an "agreement" verdict between Hub and Display (see
  Fork 3).
- This does not touch `FocusRequest`. It is a one-shot flag consumed by the
  render loop before any round trip could observe it meaningfully
  (`display/replica/frame_book.py:144-150`); there is nothing stable to
  report.
- This does not require a new wire message type. It reuses the existing
  generic `QueryRequest`/`QueryResponse` envelope
  (`protocol/messages/introspect.py:74-91`) exactly as
  `inspect_scene`/`list_scenes`/`list_recent_events`/`list_errors` already
  do.

## Part A — Display-Local Widget/Visibility State, Proxied Through the Hub

### A.1 Shape: a new standalone read, not a flag on an existing one

**Fork 1 (flag needed).** Two shapes were considered:

- **(a) Extend the two existing proxied-fact flags.** Add
  `want_widget_state` to `InspectScope`
  (`operations/models/inspect_scope.py`) so `inspect_scene` returns
  per-element widget state beside `resolved_props`, and extend the frame
  block `FrameVisibilityProxy` already fetches
  (`operations/frame_visibility_proxy.py:53-65`) with `active_tab` and
  `cascade_index` beside `visibility`.
- **(b) One new standalone operation, `get_display_state`.** Its own
  proxy, its own round trip, returning the Display's state on its own
  terms; the caller correlates it against `inspect_scene`/`list_scenes`
  results it already holds, by scene id / frame id / element id.

**Recommendation: (b).** This is what the operator described — "the Hub
exposes it through an introspection operation" — and it avoids perturbing
two wire contracts that already have committed snapshot fixtures
(`mcp-display-liveness.md`'s `ack:`-family regeneration cost applies to any
change in an existing tool's returned shape). A single bounded proxied
read is also simpler to reason about in isolation, which matters for the
concurrency question in §A.5. The one cost of (b) is a small amount of
duplication — `FramePresentation.visibility` restates a fact
`list_scenes(want_visibility=True)` already gives — accepted deliberately
so `get_display_state` is a self-sufficient one-call snapshot rather than
a partial view a caller must join with a second read.

### A.2 Wire message

No new message class. `get_display_state` is one more `method` name on the
existing generic envelope:

- Hub → Display: `QueryRequest(method="display_state", params={})`
  (`protocol/messages/introspect.py:74-80`)
- Display → Hub: `QueryResponse(method="display_state", result={...})`
  (`protocol/messages/introspect.py:83-90`)

sent over `DisplayLink.query(method, params)`
(`domain/hub/display_link.py:554-582`), the same call
`DisplayFactProxy._inspect` and `FrameVisibilityProxy._frame_blocks`
already make.

### A.3 Display side — a new query handler, registered like its siblings

`QueryRouter._query_handlers` (`display/query_dispatcher.py:50-56`) gains
one more entry, `"display_state": self._query_display_state`, implemented
beside `_query_list_scenes` (`display/query_dispatcher.py:99-130`). It
reads `self._scenes: SceneReplica` — the same object `_query_list_scenes`
already reads — and returns:

```json
{
  "scenes": {"<scene_id>": {"<element_id>": <scalar>, ...}, ...},
  "frames": [
    {"frame_id": "...", "visibility": "on_screen", "active_tab": "...", "cascade_index": 0},
    ...
  ]
}
```

`scenes` is built by a new method on `SceneReplica`,
`widget_snapshot(scene_id) -> dict[str, WireScalar] | None`, which
delegates to a new method on the class that actually owns the vocabulary,
`WidgetState.observable_snapshot()` (`display/replica/widget_state.py`) —
see §A.4 for what it includes. `frames` is built from `FrameBook.frames`
(`display/replica/frame_book.py:50-58`), reading each `Frame`'s already
public `visibility`, `active_tab`, and `cascade_index` properties
(`display/replica/frame.py:81-173`) — no new state, only a new read path
for state that already exists on the class.

### A.4 Fork 2 — curated projection vs. raw dump of `WidgetState`

`WidgetState._state` (`display/replica/widget_state.py:71-76`) is a single
flat dict keyed by element id plus a private vocabulary of suffixed keys
(`OPEN_SUFFIX`, `DISMISS_SUFFIX`, `HONOURED_SUFFIX`, `PENDING_SUFFIX`,
`CONTINUOUS_EDIT_*`, `ROW_SELECTION_*`, `FOCUS_*`, `SPLIT_RATIO_SUFFIX`) —
each is a renderer's own private arbitration bookkeeping, not a stable
domain concept.

- **(a) Raw dump.** Expose `_state` verbatim.
  - Pro: zero design cost; automatically covers any future suffix with no
    code change here.
  - Con: promotes Display-internal, renderer-private bookkeeping to a
    stable four-surface API contract (MCP/CLI/REST/library) — a renderer
    privately renaming or restructuring a suffix becomes a silent
    wire-format break. Worse, several suffixes
    (`*_PENDING_SUFFIX`, `*_EDITING_SUFFIX`, `OPEN_SUFFIX`) are true only
    for the width of a single in-flight gesture
    (`widget_state.py:47-54`'s own docstring: "pending = the fired set
    held optimistically through the gesture-to-re-push window"). Exposing
    them raw makes `get_display_state` a flaky read by construction — two
    calls a frame apart can legitimately disagree with nothing wrong,
    which is exactly the anti-pattern `python.md`'s testing standard
    (PL-TT-4) rules out for tests and applies equally to a verification
    surface.
- **(b) Curated projection (recommended).** A new method,
  `WidgetState.observable_snapshot() -> dict[str, WireScalar]`
  (`WireScalar = str | float | bool | tuple[str, ...]`, justified as a
  wire boundary per PY-TS-14 — see §A.6), returning:
  - the bare per-element value (whatever `get_str`/`get_float`/`get_bool`
    would read for that id) — the current in-progress text, scroll
    position, or numeric/flag value a widget is holding;
  - the durable, non-gesture-window session facts: the *honoured* (not
    *pending*) tab and header-open state, the *honoured* (not *pending*)
    row selection, the *committed* (not *editing*) continuous-edit value,
    `focus_seen`, and the split ratio.
  - excluding every `OPEN`/`DISMISS`/`*_PENDING`/`*_EDITING` slot — these
    are true only mid-gesture and are not a fact worth comparing against
    the Hub's steady-state view.

  Cost: this method must be extended whenever a new suffix category is
  added to `WidgetState` — but PY-OO-5 puts that cost exactly where it
  belongs: on the class that owns the vocabulary, right beside the
  constant it must be taught to recognize, not in a second place that can
  drift from the first.

**Recommendation: (b).** A verification surface that is sometimes-flaky by
design defeats its own purpose.

### A.5 Concurrency — no new risk, no z-spec required

I checked whether this crosses a thread boundary the way the
`HubReplicator`/`HubDisplay` lock work did (`mcp-display-liveness.md`
§"Concurrency verification"). It does not. `SocketListener.poll_clients`
(`display/socket_server.py:193-197`) is a non-blocking `select.select(...,
0)` poll, invoked once per render frame from the render loop's own thread;
`_handle_message` → `_handle_readonly_message` → `_handle_query` →
`QueryRouter.handle_query` (`display/render_loop.py:602-638,682-685`) all
run on that same single thread — the identical call path
`_handle_list_scenes` and `_handle_introspect` already use today to read
`SceneReplica` with no lock. A `display_state` handler reading
`WidgetState._state` (also only ever mutated by ImGui widget calls on this
same render-loop thread) inherits that existing single-threaded safety
property; it introduces no interleaving that does not already exist for
`list_scenes`. This is "purely sequential logic" per the z-spec section of
`CLAUDE.md` — no model-check is required. (If a future change moves query
handling onto its own thread, that change would need the z-spec treatment
for the whole `QueryRouter` surface, not specially for this handler.)

### A.6 Hub side — models and proxy

New module `operations/models/display_state.py`:

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from punt_lux.operations.models.query_visibility import FrameVisibility

__all__ = ["DisplayStateSnapshot", "FramePresentation", "WidgetSnapshot"]

# WidgetState's keys are the per-render-frame bookkeeping vocabulary each
# ImGui renderer privately owns (display/replica/widget_state.py); Lux does
# not recreate a typed domain model for arbitrary renderer-defined keys
# here (PY-TS-14 wire boundary) — the curated set of names
# ``observable_snapshot`` emits is the contract, not this value's type.
type WireScalar = str | float | bool | tuple[str, ...]


class WidgetSnapshot(BaseModel):
    """One scene's curated Display-local widget state, keyed by element id."""

    model_config = ConfigDict(frozen=True)

    values: dict[str, WireScalar]


class FramePresentation(BaseModel):
    """One frame's Display-owned facts (DES-088) — never Hub-authoritative."""

    model_config = ConfigDict(frozen=True)

    frame_id: str
    visibility: FrameVisibility
    # None is a real state, not "unknown": a frame with no scenes has no
    # active tab to report.
    active_tab: str | None
    cascade_index: int


class DisplayStateSnapshot(BaseModel):
    """The Display's own state, read once, for Hub-vs-Display comparison."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["ok"] = "ok"
    scenes: dict[str, WidgetSnapshot]
    frames: list[FramePresentation]
```

New class `operations/display_state_proxy.py`, structurally identical to
`DisplayFactProxy` (`operations/display_facts.py`):

```python
@final
class DisplayStateProxy:
    """Proxy the Display's own widget/frame state, narrowed to a snapshot."""

    _port: DisplayPort
    __slots__ = ("_port",)

    def __new__(cls, port: DisplayPort) -> Self:
        self = super().__new__(cls)
        self._port = port
        return self

    def snapshot(self) -> DisplayStateSnapshot | OpError:
        payload = self._port.query("display_state", {}).resolve()
        if isinstance(payload, OpError):
            return payload
        return DisplayStateSnapshot.from_payload(
            payload
        )  # raises ValueError on malformed
```

`QueryOperations` (`operations/queries.py:41-59`) gains a `_state:
DisplayStateProxy` slot built alongside `_facts` and `_scenes` at
`operations/queries.py:56-58`, and a `display_state()` method beside
`list_recent_events`/`list_errors` (`operations/queries.py:113-125`).
`Operations` (`operations/facade.py`) gains `get_display_state()` beside
`get_theme()`/`get_window_settings()` (`operations/facade.py:207-221`) —
plain delegation, `OpError`-or-result, exactly like every other standalone
display-fact read; no `InspectScope` involved, because this is its own
tool call, not an opt-in flag on someone else's.

**Scene-id normalization.** The Display's `SceneReplica` keys scenes by
whatever id the Hub last pushed under (the composed store key, per
`domain/hub/connection_scoped_id.py`). `DisplayStateProxy.snapshot()`
should strip each `scenes` key back to the caller's own local id with
`SceneListing.local_id_of` (`operations/queries.py:106-109`), the same
composition-boundary step `ClientListing._client` already applies to
`owned_scenes` (`operations/client_listing.py:84-89`) — so a caller can
correlate `get_display_state()`'s keys directly against the scene ids
`inspect_scene`/`list_scenes` already handed it, with no re-composition on
its part.

### A.7 Four-surface parity

Following the `session_ls` shape (`commands/session_ls.py`) exactly:

| Surface | Touchpoint |
|---|---|
| Operations (engine) | `Operations.get_display_state()` (`operations/facade.py`) |
| Commands | new `commands/display_state_get.py`: `DisplayStateGetCommand`, singleton `display_state_get`, `execute(ctx) -> DisplayStateSnapshot \| OpError`, `__call__` renders `CommandResult` |
| MCP tool | `tools/read_tools.py`, name `display_state_get` — matching the `display_window_get`/`display_theme_get` naming already in use for single-object display reads (`tools/read_tools.py:170-186`) |
| CLI | `cli/display.py`, `lux display state` — beside `lux display window get`/`lux display theme get` |
| REST | `rest/display.py`, `GET /display/state` — beside the existing `/display/*` routes |
| Library | `client/_rest_display.py`, a `display_state()` method mirroring its existing `theme()`/`window_settings()` calls |

One vocabulary, one name (`display_state`/`get_display_state`), across all
six touchpoints, per `architecture.md`'s "one vocabulary across the four
surfaces" rule.

### A.8 Fork 3 — does the Hub compute agreement, or only report facts?

- **(a) The Hub computes a verdict.** `DisplayStateSnapshot` (or a
  wrapping operation) also reads `HubDisplay`'s own view and returns
  `matches_hub: bool` / a mismatch list.
  - Con: this requires deciding, inside the engine, what "agreement"
    means per element kind — and several of the values `observable_snapshot`
    reports are *expected* to differ from the Hub's last-known value for a
    real, non-buggy reason (a slider mid-drag, a row-selection gesture in
    flight). Baking a verdict in means baking in a per-widget-kind
    tolerance policy the operator has not specified, and every existing
    proxied fact in this codebase — `DisplayFactProxy`, `FrameVisibilityProxy`
    — deliberately stops at reporting the fact, never a verdict
    (`introspection-api.md`: "Introspection is about live Lux state... not
    to infer outcomes from implementation details").
- **(b) The Hub reports facts only (recommended).** A caller wanting an
  automated comparison builds it from `get_display_state()` plus its own
  `inspect_scene()`/`list_scenes()` calls, correlated by scene id / frame
  id / element id — the same shape every other proxied fact in this
  codebase already uses.

**Recommendation: (b)**, for consistency with the established pattern and
to avoid the engine taking an unspecified position on what "agreement"
means.

## Part B — Hub-Side Connection Lifecycle: Writer Binding and Inbox Depth

`list_clients` (`operations/models/query_clients.py:15-27`) already
reports `subscribed_topics` and `owned_scenes` per session — the
subscription half of the gap is closed. What is missing is whether a
writer is bound, and how deep the connection's inbox queue is.

### B.1 `writer_bound` — already available, just unread here

`Hub.has_writer(connection_id)` (`domain/hub/hub.py:81-83`) already
answers this exactly. `ClientListing._client`
(`operations/client_listing.py:65-90`) already holds `self._hub` and
already calls `self._hub.topics_for(connection_id)` on the next line up —
adding `writer_bound=self._hub.has_writer(connection_id)` is a one-line
addition to an existing method, using an existing public accessor.

### B.2 `inbox_depth` — one new accessor, following the existing port pattern

The per-connection inbox queues live in `domain/hub/inbox.py` as a
module-level `dict[ConnectionId, queue.SimpleQueue[ObserverMessage]]`
(`domain/hub/inbox.py:31-32`), guarded by `_inboxes_lock`. `Hub` cannot
import `inbox.py` to expose this directly — `inbox.py` already imports
`from punt_lux.domain.hub.hub import hub` (`domain/hub/inbox.py:14`), so a
`Hub → inbox` import would be a cycle (PL-CU-2).

This is exactly the shape `HubPorts` already exists to solve — `inbox.py`
already supplies two of its callable ports, `ensure_writer` and
`next_event` (`operations/ports.py:27-30`, wired at
`hub_composition.py:20,73-78`). A third,
`inbox_depth: Callable[[ConnectionId], int]`, is added the same way:

```python
# domain/hub/inbox.py — one more function beside next_event, same style
def inbox_depth_for(connection_id: ConnectionId) -> int:
    """Return the connection's queued-but-undelivered event count.

    Approximate under concurrent puts, per queue.SimpleQueue.qsize()'s own
    contract — good enough for an observational read; never used for
    control flow.
    """
    with _inboxes_lock:
        inbox = _inboxes.get(connection_id)
    return inbox.qsize() if inbox is not None else 0
```

```python
# operations/ports.py — one more port, same shape as EnsureWriter/NextEvent
type InboxDepth = Callable[[ConnectionId], int]


@dataclass(frozen=True, slots=True)
class HubPorts:
    element_factory: ElementFactoryFor
    ensure_writer: EnsureWriter
    next_event: NextEvent
    inbox_depth: InboxDepth  # new
    display_port: DisplayPort
```

```python
# hub_composition.py:20,73-78 — wire the new port the same way as the other two
from punt_lux.domain.hub.inbox import ensure_writer, inbox_depth_for, next_event

...
return HubPorts(
    element_factory=hub_element_factory,
    ensure_writer=ensure_writer,
    next_event=next_event,
    inbox_depth=inbox_depth_for,
    display_port=cls.display_port(),
)
```

`ClientListing` (`operations/client_listing.py:36-40`) takes one more
constructor argument, `inbox_depth: InboxDepth`, threaded down from
`QueryOperations.__new__` (`operations/queries.py:52-59`, which already
receives `HubPorts` via `Operations.for_store`,
`operations/facade.py:118-145`, specifically the `ClientListing(display,
hub)` call at `operations/queries.py:58`).

### B.3 `HubClient` gains two fields — no new operation, no new tool

`operations/models/query_clients.py:15-27` gains:

```python
class HubClient(BaseModel):
    model_config = ConfigDict(frozen=True)

    connection_id: str
    identity: ClientIdentity | None = None
    connected_seconds: float
    lease: LeaseTerm
    subscribed_topics: list[str]
    owned_scenes: list[str]
    writer_bound: bool  # new
    inbox_depth: int  # new
```

populated in `ClientListing._client` (`operations/client_listing.py:76-90`):

```python
return HubClient(
    ...,
    writer_bound=self._hub.has_writer(connection_id),
    inbox_depth=self._inbox_depth(connection_id),
)
```

This rides the *existing* `list_clients`/`session_ls` operation, MCP tool,
CLI command, and REST route (`operations/queries.py:98-101`,
`tools/read_tools.py:188-198`, `cli/session.py`, `rest/scenes.py:244-247`)
— no new touchpoint needed anywhere in Part B; it is a field addition to
an already-shipped four-surface contract. This is deliberately the
smallest possible change that closes the gap: both new facts sit exactly
beside `subscribed_topics`/`owned_scenes`, which already carry the same
"per-connection lifecycle fact, Hub-authoritative, no display round trip"
shape.

### B.4 Why this is enough for `lux-vvmt` and `lux-95zt`

- **Lease-reap cascade convergence (`lux-vvmt`).** A reap that departs a
  connection must leave it with no writer and no lingering inbox — before
  this change, that could only be inferred indirectly (does a later
  publish silently vanish?). After: `list_clients()` before and after a
  reap directly shows `writer_bound` flip to absent-from-roster (the
  connection itself should stop appearing — `has_writer` and the roster
  entry are dropped together, see `LeaseReapSweep`/`HubDisplay
  .reap_lapsed_leases`) and, for a connection observed mid-reap-window, a
  non-decreasing `inbox_depth` would be exactly the "queue nobody's
  draining" signature a convergence test needs to assert against.
- **Twin-subscription-loss (`lux-95zt`).** Two sessions on one connection
  (a superseding identity) each install a writer and subscriptions;
  `writer_bound` tells you whether *a* writer is bound at all, and
  `subscribed_topics` (already shipped) tells you which topics survive a
  handoff. A test can subscribe twice, supersede, and assert the surviving
  session's topics are exactly what should remain — not silently zero.

## OO Compliance

Two BEFORE/AFTER pairs cover every new type this design introduces.

**PY-OO-5 / PY-OO-7 (state owns its own projection, not a helper beside
it) — `WidgetState.observable_snapshot`:**

```python
# BEFORE (rejected, Fork 2 option (a)) — a query-dispatcher helper reaches
# into another class's private dict and re-derives its own idea of what's
# "public", duplicating knowledge WidgetState already encodes in its own
# suffix constants.
def _query_display_state(self, **_kwargs: Any) -> dict[str, Any]:
    scenes = {}
    for scene_id, ws in self._scenes._by_scene.items():  # reaches into private state
        scenes[scene_id] = {
            k: v for k, v in ws._state.items()
            if not k.endswith((":row_selection_pending", ":continuous_edit_editing", ...))
        }
    return {"scenes": scenes, ...}
```

```python
# AFTER — the class that owns the suffix vocabulary owns the projection.
class WidgetState:
    ...

    def observable_snapshot(self) -> dict[str, WireScalar]:
        """The curated, comparison-worthy subset of this scene's widget state.

        Bare per-element values plus the durable *honoured*/*committed*
        session facts; every *pending*/*editing*/*open*/*dismissed* slot is
        excluded because it is true only for the width of one in-flight
        gesture, never a steady-state fact worth reporting.
        """
        return {
            key: value for key, value in self._state.items() if self._is_observable(key)
        }

    @classmethod
    def _is_observable(cls, key: str) -> bool:
        return not key.endswith(
            (
                cls.OPEN_SUFFIX,
                cls.DISMISS_SUFFIX,
                cls.PENDING_SUFFIX,
                cls.HEADER_OPEN_PENDING_SUFFIX,
                cls.CONTINUOUS_EDIT_BUFFER_SUFFIX,
                cls.CONTINUOUS_EDIT_EDITING_SUFFIX,
                cls.ROW_SELECTION_PENDING_SUFFIX,
            )
        )
```

`display/query_dispatcher.py`'s new handler then only calls
`scene_replica.widget_snapshot(scene_id)`, never reaches into
`WidgetState`'s or `SceneReplica`'s private fields.

**PY-TS-14 (justify the wire-boundary type, discriminate the outcome
rather than nesting an Optional) — the proxy's result:**

```python
# BEFORE (rejected) — an Optional return whose None could mean "not
# running", "timed out", or "malformed reply", forcing every caller to
# re-derive which.
def snapshot(self) -> DisplayStateSnapshot | None:
    payload = self._port.query("display_state", {}).resolve()
    if isinstance(payload, OpError):
        return None
    return DisplayStateSnapshot.from_payload(payload)
```

```python
# AFTER — discriminated: OpError already names display_unavailable /
# timeout / rejected (operations/display_reply.py:19-73); the caller
# always knows exactly which of "here it is" or "here is why not" it got.
def snapshot(self) -> DisplayStateSnapshot | OpError:
    payload = self._port.query("display_state", {}).resolve()
    if isinstance(payload, OpError):
        return payload
    return DisplayStateSnapshot.from_payload(payload)
```

Every new field on `HubClient`, `WidgetSnapshot`, and `FramePresentation`
is either a total type (`bool`, `int`, `dict[str, WireScalar]`) or a
justified `str | None` (`FramePresentation.active_tab`, where `None` is
the documented "no scenes in this frame" state, not a failure) — no bare
`Any` and no unjustified Optional anywhere in this design (PY-TS-9,
PY-TS-14).

## Backwards Compatibility

- `HubClient` gains two required fields (`writer_bound`, `inbox_depth`).
  This changes `list_clients`/`session_ls`'s wire shape — a real,
  intentional break of that contract's field set, not additive-only,
  because both new fields are meaningful for every existing client and a
  `| None` "didn't ask" placeholder would misrepresent a fact the Hub
  always knows. Existing snapshot fixtures for `session_ls` need
  regenerating (the same category of update `mcp-display-liveness.md`
  already documents for its own wire-shape changes).
- `get_display_state` is new — no existing surface changes shape.
- Nothing here changes `inspect_scene`'s or `list_scenes`'s wire shape
  (Fork 1 recommendation (b) was chosen specifically to avoid that).

## Proposed Write-Set (implementation phase — not done in this mission)

Engine:

- `src/punt_lux/display/replica/widget_state.py` — `observable_snapshot`
- `src/punt_lux/display/replica/scene_replica.py` — `widget_snapshot(scene_id)`
- `src/punt_lux/display/query_dispatcher.py` — `"display_state"` handler
- `src/punt_lux/domain/hub/inbox.py` — `inbox_depth_for`
- `src/punt_lux/operations/ports.py` — `InboxDepth`, `HubPorts.inbox_depth`
- `src/punt_lux/hub_composition.py` — wire the new port
- `src/punt_lux/operations/models/display_state.py` — new module (§A.6)
- `src/punt_lux/operations/display_state_proxy.py` — new module (§A.6)
- `src/punt_lux/operations/models/query_clients.py` — `HubClient` fields (§B.3)
- `src/punt_lux/operations/client_listing.py` — populate the new fields
- `src/punt_lux/operations/queries.py` — wire `DisplayStateProxy`, thread `inbox_depth`
- `src/punt_lux/operations/facade.py` — `get_display_state()`

Four-surface parity:

- `src/punt_lux/commands/display_state_get.py` — new
- `src/punt_lux/commands/__init__.py` — export it
- `src/punt_lux/tools/read_tools.py` — MCP tool `display_state_get`
- `src/punt_lux/cli/display.py` — `lux display state`
- `src/punt_lux/rest/display.py` — `GET /display/state`
- `src/punt_lux/client/_rest_display.py` — library `display_state()`

Tests (every changed/new module per `python.md`'s testing pyramid, plus
surface-parity tests per its Surface Parity Testing section):

- `tests/test_widget_state.py` — `observable_snapshot` roundtrip, gesture-window exclusion
- `tests/test_scene_replica.py` — `widget_snapshot`
- `tests/test_query_dispatcher.py` — `"display_state"` handler shape
- `tests/test_display_state_proxy.py` — new, `DisplayReply` → `OpError`/`DisplayStateSnapshot` narrowing
- `tests/test_client_listing.py` — `writer_bound`/`inbox_depth` population
- `tests/test_inbox.py` — `inbox_depth_for`
- new `display_state` surface-parity test (MCP tool ⟷ CLI ⟷ REST ⟷ library), following `tests/test_switches_surface_parity.py`'s shape (`python.md` § Surface Parity Testing)
- `session_ls`/`list_clients` snapshot-fixture regeneration for the two new `HubClient` fields

Docs (to update once implemented, not part of this design mission):

- `docs/architecture/target/introspection-api.md` — add `get_display_state`
  to the read-only surface list (line 22-31) and a short paragraph under
  "Implementation Note"
- `DESIGN.md` — new ADR, candidate `DES-091` (next after `DES-090`)
- `CHANGELOG.md` — `## [Unreleased]`

## Open Decisions For The Operator

1. Fork 1 — standalone `get_display_state` operation (recommended) vs.
   extending `InspectScope`/`inspect_scene`/`list_scenes` in place.
2. Fork 2 — curated `observable_snapshot` projection (recommended) vs.
   raw `WidgetState._state` dump.
3. Fork 3 — facts-only proxy (recommended) vs. a Hub-computed
   agreement/mismatch verdict.
