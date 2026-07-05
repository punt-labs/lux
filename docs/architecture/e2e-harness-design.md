# End-to-End Business-Event Loop Harness — Design

**Status:** ratified design. In-process, no socket, no subprocess, no GPU.
No code yet. The leader reviews this revision, then dispatches implementation.
The three previously-open decisions are resolved (see [Ratified
design](#ratified-design) at the end); the GPU/pixel layer is dropped from
current scope.

## Threat this design addresses

The threat is not an attacker. It is **the illusion of progress** — a green
test suite that certifies a loop nobody has actually run across the real
boundary.

Every migrated element is unit-tested for render, validate, and fire in
isolation. The Round-trip procedure in [`tests/CLAUDE.md`](../../tests/CLAUDE.md)
names the failure mode: "A green Level 1 over a stubbed Level 4 is the exact
failure mode that has bitten this project before." Three pieces of
infrastructure each prove a *different slice* of the loop, and **none proves the
whole loop through the production Hub dispatch**:

- [`tests/test_e2e.py`](../../tests/test_e2e.py) drives a real display
  subprocess over a real Unix socket and fires an interaction
  (`--test-auto-click`, `test_e2e.py:123`), **but the receiving end is a test
  callback** (`client.on_event`, `test_e2e.py:152`) — not the real Hub dispatch,
  no `HubDisplay` resolve, no real handler, no publish, no re-push.
- [`tests/integration/test_subscribe_publish.py`](../../tests/integration/test_subscribe_publish.py)
  drives the real MCP pub/sub tool surface (`subscribe`/`publish`/`drain_inbox`,
  lines 39-102), **but the publish is called directly** — never triggered by a
  UI interaction crossing the Hub/Display boundary.
- [`tests/regression/test_dialog_interaction_trace.py`](../../tests/regression/test_dialog_interaction_trace.py)
  pins the full causal chain for a Confirm click — fire → `DialogModel.confirm`
  → `mark_removed` → observer cascade → publish to a subscriber
  (`test_dialog_interaction_trace.py:233-361`) — **but entirely through the
  test-only `Display.interact`** (`domain/display.py:19-25`) with a test
  `_publish_sink` (`line 252`), not through the production Hub dispatch.

No standing gate asserts that a UI interaction produces the **exact wire event a
real click produces**, crosses the Hub/Display boundary through the same
`Connection` interface the real transport uses, runs the real handler **once** on
the Hub's authoritative copy, publishes a business event a **real subscriber**
receives, and — when the agent reacts — carries a change **back** to the
Display's replica, all on the **composed** migrated surface. This design makes
that full bidirectional loop a standing, CI-capable gate every future element
rides.

## The production loop, as it actually runs

The harness must exercise the **production** dispatch path, not the in-process
test contract. The two are different code, and conflating them is how the
illusion forms.

The real loop (all citations to shipped code):

1. **Display tier** wraps every handler for remote dispatch on scene receipt —
   `DisplayServer._wrap_abc_elements` calls `elem.wrap_handlers_for_remote`
   with `self._emit_event` as the send path (`display/server.py:935-946`).
2. **Emit point** — a fired handler (or the test-mode auto-click loop) calls
   `DisplayServer._emit_event(RemoteEventHandlerInvocation(...))`
   (`server.py:802-819`), which stamps `scene_id` and queues the invocation;
   `_flush_events` drains the queue and sends each invocation to the Hub
   (`server.py:1533-1562`).
3. **Hub dispatch** — the Hub's `DisplayClient` fallback handler is
   `ClientRegistry._hub_interaction_dispatch`
   (`domain/hub/clients.py:95`, definition at `clients.py:100`). It resolves the
   element from the authoritative `HubDisplay` (`hub_display.resolve`,
   `clients.py:129`), constructs the typed `ButtonClicked`/`ValueChanged`
   (`clients.py:168-179`), and fires it **once** at the single dispatch site
   `element.fire(event)` (`clients.py:194`).
4. **Business event** — the fired handler's `publish` decorator reaches
   `hub.publish(connection_id, topic, payload)` (`domain/hub/hub.py:89-119`).
   Fan-out is connection-scoped: session A's click never publishes into session
   B's topics (`hub.py:95-105`).
5. **Real subscriber** — `hub.publish` invokes the connection's registered
   writer, which enqueues onto the session inbox (`tools/inbox.py:83-86`);
   `next_event`/`recv` consumes one (`inbox.py:64-70`), `drain_inbox` snapshots
   all (`inbox.py:43-61`).
6. **Re-push** — the same dispatch re-sends the full scene tree via
   `client.show_async(...)` (`clients.py:199-208`). The Display replaces its
   replica.

The test-only `Display.interact` (`domain/display.py:19-25`) is a **different**
in-process dispatch surface — its own docstring says so: "Under D21 the display
forwards interactions to the Hub … production interaction dispatch runs on the
Hub side; `interact` here stays the in-process dispatch contract." **The harness
dispatches through `_hub_interaction_dispatch`, never `Display.interact`.** Using
the latter would re-create the exact in-process illusion this harness exists to
kill.

## In-process, no socket, no subprocess, no GPU

The harness runs the Hub logic and the Display logic in **one process**, wired
through the shipped `InMemoryConnection`
([`protocol/in_memory_connection.py`](../../src/punt_lux/protocol/in_memory_connection.py)).

### Why the in-memory connection is a faithful boundary, not a stub

`InMemoryConnection` exposes the **identical** `send_line` / `iter_lines` /
`close` shape as the real `LineSocket` wire transport
(`protocol/connection.py:59-81`). Both are documented as interchangeable
backends: `connection.py:7-9` states both "expose the same `send_line` /
`iter_lines` / `close` shape so consumers don't branch on backend," and
`in_memory_connection.py:47-53` describes the paired-queue duplex "matching the
`LineSocket` shape." A consumer written against that three-method interface
cannot tell which backend carries its frames. Crossing the boundary through
`InMemoryConnection` therefore exercises the **same abstraction** the socket
exercises — it is a faithful boundary, not a mock of one.

**Correctness caveat, stated plainly.** The current production
`DisplayClient` ↔ `DisplayServer.SocketServer` path does **not** yet run on
`LineSocket`; per `connection.py:10-11`, "`DisplayClient` keeps its existing
length-prefixed wire path until a coordinated cross-tier flip." The harness
therefore drives the **migration-target** `Connection` interface
(`LineSocket` / `InMemoryConnection`), which is byte-faithful to the real socket
transport but is not the exact length-prefixed framing today's `DisplayClient`
ships. This is the operator-ratified shape: exercise the faithful `Connection`
abstraction in-process. The implementing specialist owns the exact wiring of the
Display's outbound emit and the Hub's inbound dispatch onto that interface.

### The Display's receive/wrap/emit logic runs without the render loop

The ImGui render loop is not needed to run the loop under test. `DisplayServer`'s
own module docstring says it "can be imported by unit tests (for state machine
testing) but `run()` requires a GPU-capable environment" (`server.py:9-12`).
Only `run()` (`server.py:422`) opens a window; the receive path
(`_handle_scene`, `server.py:905`), the handler-wrapping
(`_wrap_abc_elements`, `server.py:935-946`), and the emit point (`_emit_event`,
`server.py:802-819`) are ordinary methods callable in-process with no window.

This is already demonstrated:
[`tests/test_display_rebind.py`](../../tests/test_display_rebind.py) constructs a
real `DisplayServer` with no socket bound (`test_display_rebind.py:50-53`) and
drives `_wrap_abc_elements` directly to prove the rebind-and-wrap logic
(`test_display_rebind.py:71-114`).
[`tests/integration/test_text_outbound_e2e.py`](../../tests/integration/test_text_outbound_e2e.py)
is the in-process precedent for the transport: it constructs the boundary with
`InMemoryConnection.paired()` (`test_text_outbound_e2e.py:46,82`) and ships a
real wire dict client → hub end without a socket or subprocess.

The one deliberate omission is the pixel paint. By
[target.md](./target/target.md) §Communication Model, "UI state crosses IPC;
render calls do not." Omitting the paint removes nothing that crosses the loop.
The
[`RaisingRendererFactory`](../../src/punt_lux/protocol/renderers/raising.py)
enforces this: bound off the wire before rebind (`test_display_rebind.py:56-68`),
any accidental `render()` call **fails loud** rather than silently passing.

### CI capability

Because there is no GPU, no subprocess, and no OS socket, the harness runs as a
**Tier-2 integration test** (`@pytest.mark.integration`, per
[`tests/CLAUDE.md`](../../tests/CLAUDE.md) pyramid) — in CI, on every PR. The
entire CI-capability claim rests on the two verified facts above: the
`Connection` interface is shared between `InMemoryConnection` and `LineSocket`,
and the Display's receive/wrap/emit logic runs without the render loop.

## Addressable injection at our own event layer

A real click and a test click become **byte-identical** at
`DisplayServer._emit_event(RemoteEventHandlerInvocation(...))`. The existing
test-mode auto-click loop already emits there: `_auto_click_emit_loop`
(`server.py:969-1058`, called via `_auto_click_buttons`, `server.py:952-967`)
constructs a `RemoteEventHandlerInvocation` per element and hands it to
`_emit_event`. That is the same `_emit_event` the production `remote_dispatch`
handler-wrapping captures (`server.py:806-809`). No wire control message, no
ImGui event, no fake path — the injection is the **real event at the real
layer**.

The only change the harness needs is **addressability**. Today's auto-click
loop fires **every** interactive element in the scene (`server.py:969-1058`) —
non-deterministic for a composed scenario with several interactive children.
The harness targets **one** `element_id` with **one** action and value. The
design is a thin generalization of the existing loop: a test-facing method (or
hook) on the Display — call it, for illustration, `inject(element_id, action,
value)` — that constructs the same `RemoteEventHandlerInvocation` shape
`_auto_click_emit_loop` already builds for that element kind and passes it to
`_emit_event`. It is a **test-facing method on the Display, not a
protocol/wire message**. The specialist owns the exact signature and placement.

**Deferred assumption (see [Deferred](#deferred-visual--injection-fidelity-proof)).**
This asserts our `_emit_event` injection produces the invocation a real click
produces — true by construction today, because a real GLFW/ImGui click and the
injection both call `_emit_event` with the same `RemoteEventHandlerInvocation`
shape (`server.py:935-946` wires the click path through the identical emit
point). Pixel-level fidelity — that a real GLFW window click emits that exact
event — is **deferred** with the visual/screenshot layer.

## The loop is bidirectional and agent-driven

The driver is a **simulated agent** using the real client/tool surface: `show`,
`subscribe`, the addressable inject, `recv`/`drain_inbox`, `update`,
`inspect_scene`. The return path — the agent reacting to the published event by
mutating the UI — is a **first-class asserted invariant**, not a footnote.

The full circle:

1. **show** — the agent `show`s a composed surface (a `group` holding a `button`
   and a `progress`); the Hub installs it in `HubDisplay` and pushes a replica to
   the Display logic.
2. **subscribe** — the agent subscribes an app topic and binds a real inbox
   writer via `ensure_writer` (`tools/inbox.py:73-86`).
3. **inject** — the agent injects one addressable interaction; the Display's
   `_emit_event` produces the exact `RemoteEventHandlerInvocation` a real click
   produces.
4. **dispatch** — the invocation crosses the in-memory `Connection` to the
   **production** `_hub_interaction_dispatch` (`clients.py:100`), which resolves
   the element on the authoritative `HubDisplay` and fires the real handler
   **once** (`clients.py:194`).
5. **publish** — the handler publishes an app topic through `hub.publish`
   (`hub.py:89-119`).
6. **recv** — the simulated agent **receives** it from the real inbox via
   `recv`/`next_event` or `drain_inbox` (`inbox.py:43-70`).
7. **agent reacts / update** — the agent reacts to the announcement by pushing a
   change **back**: an `update` that replaces part of the scene (e.g. advances
   the `progress`, relabels the `button`).
8. **re-push** — the Hub re-pushes the full affected scene (`clients.py:199-208`
   for the handler-driven re-push; the agent's `update` drives the same
   replace-the-replica path).
9. **verify** — the agent verifies **both directions** via introspection:
   `inspect_scene` shows the replica reflecting the mutation, and the subscriber
   inbox shows the business event delivered exactly once.

### Sequence

```text
Simulated agent          Hub (in-process)                 Display logic (no GPU)
--------------           ----------------                 ----------------------
show(group[button,       install in HubDisplay ---push---> hold replica; wrap
      progress]) ------->                                  handlers -> _emit_event
subscribe(topic) ------> ensure_writer(conn): real inbox
                                                           inject(button_id,
inject -----------------------------------------------.    clicked) builds
                                                      |    RemoteEventHandler-
                          _hub_interaction_dispatch  <'--- Invocation via
                          resolve on HubDisplay            _emit_event
                          element.fire(event) ONCE
                          handler -> hub.publish(topic)
recv()/drain_inbox() <--- deliver to real inbox (==1)
agent REACTS:
update(progress=...) ---> replace in HubDisplay --push--> replica reflects
                                                           mutation
inspect_scene() <-------- (both directions verified: replica mutated +
                          inbox delivered exactly once)
```

## The loop invariants the harness asserts

Each is asserted through the introspection APIs or the real subscriber inbox —
never through an internal stub of the dispatch, handler, publish, or inbox.

- **I1 — Faithful-boundary crossing.** The interaction originates at the
  Display's `_emit_event` as the exact `RemoteEventHandlerInvocation` a real
  click produces, and crosses to the Hub through the shared `Connection`
  interface. Not hand-constructed on the Hub side; the invocation is produced by
  the Display-tier emit path and read by the Hub's dispatch.
- **I2 — Hub-authoritative, exactly once.** The real handler runs **once**, on
  the Hub's `HubDisplay` copy. Asserted by its single observable effect: publish
  delivered exactly once (I3) and Hub-side model state transitioned exactly once
  (e.g. `dialog.confirmed` flips `False`→`True`, never double-applied).
- **I3 — Business event published and received.** The handler's `publish`
  decorator fires an app topic; a **real subscriber** receives it. Asserted via
  `drain_inbox`/`recv` on the owning connection — `delivered == 1`,
  `inbox[0].topic == <topic>`, payload matches. Never via a test publish-sink.
- **I4 — Recv / ask-user response (where applicable).** For ask-user flows the
  handler produces a `recv`-consumable response on the same inbox surface.
  Asserted through `recv`, not an internal return value.
- **I5 — Return-path replica fidelity (bidirectional).** After the agent reacts
  with `update`, the Hub re-pushes and the Display replica reflects the change.
  Asserted via `inspect_scene` (`render_path`, `resolved_props`) — the mutation
  is present in the replica, and only via the re-push, not a local Display edit.
  This is the asserted return half of the loop, not a side note.
- **I6 — Two mechanisms kept distinct.** UI handler/observer dispatch (D21) and
  Hub application pub/sub are asserted **independently** (see
  [target.md](./target/target.md) §Event Models). A handler may fire UI behavior
  **and** publish a business event; the harness asserts each separately and
  fails if either is missing or if one is used to fake the other.

### The central invariant: no stub of the boundary

Every assertion above observes the running system through the introspection APIs
or the real subscriber inbox. The harness **must not** stub the loop under test:
no test `_publish_sink`, no `MagicMock` of the Hub `DisplayClient` or dispatch,
no hand-constructed `RemoteEventHandlerInvocation` fed straight into
`_hub_interaction_dispatch`, no `Display.interact`. The interaction originates at
the Display's `_emit_event`; the Hub dispatch, the real handler, `hub.publish`,
and the real inbox all run for real.

The `InMemoryConnection` is **not** a boundary stub under this rule: it
implements the identical `Connection` interface (`send_line`/`iter_lines`/`close`)
that the real `LineSocket` implements (`connection.py:7-9`,
`in_memory_connection.py:47-53`), so the boundary is crossed through the same
abstraction, not around it. The one deliberate omission — GPU paint — is guarded
by `RaisingRendererFactory`: any accidental render call fails loud, converting
"we didn't render" from an unstated assumption into a proven property.

## Scenario framework

The harness exercises the **composed** migrated surface, and adding a future
element must be cheap. A scenario is **declarative data**, not a bespoke test
function.

### Scenario shape

```text
Scenario:
  name:        stable identifier (e.g. "group-button-progress")
  compose:     the element tree to show()  (e.g. a `group` holding a
               `button` + a `progress`)
  handler:     the Hub-side handler wiring for the target element
               (e.g. call_model verb + publish decorator on topic X)
  subscribe:   the app topic(s) the agent subscribes before injecting
  inject:      (target_element_id, action, value) — the single deterministic
               addressable interaction
  react:       the agent's update() reaction to the published event —
               the mutation it pushes back (the return-path half)
  expect:
    published:   topic + payload the subscriber inbox must receive (I3)
    fired_once:  the Hub-side state transition that must occur exactly once (I2)
    repush:      the replica mutation inspect_scene must reflect after react (I5)
    ui_effect:   the view-logic effect, asserted independently of publish (I6)
```

The loop invariants (I1–I6) are expressed **once** in the harness and run
against **every** scenario. Adding an element means adding a `Scenario` value,
not new assertion code. "Migrated" then means "its full bidirectional
interaction + business-event loop is green in the harness," not merely "it
paints."

### First scenario — the composed migrated surface

A `group` (container) holding an interactive `button` and a display-only
`progress` — the composition the operator named. The button's Hub-side handler
runs a `call_model` verb (view logic) **and** publishes a business topic
(business logic). The harness asserts: the injected click crosses the faithful
boundary (I1), fires once on the Hub (I2), publishes the topic to the real
subscriber (I3), the agent reacts with an `update` that the re-pushed replica
reflects (I5), and the view effect and the published event are each present
**independently** (I6). `progress` rides as a display-only leaf whose presence in
the re-pushed replica is asserted, proving the container round-trips a mixed
interactive/non-interactive composition.

### Per-element extension point

Each newly migrated interactive kind adds one `Scenario` naming its target
event, its handler wiring, its expected publish, and its agent reaction. The
[Round-trip procedure](../../tests/CLAUDE.md) Level 4 becomes "the kind has a
green Scenario in this harness." A structural guard scenario asserts that a new
container kind exposes its children to the injection walk — the same discipline
as the `child_elements()` guard for validation — so a composite can never
silently hide an interactive child from the loop gate.

## Security / trust-boundary properties (my lens)

The `Connection` interface is the trust boundary; the harness makes three
boundary properties standing gates. These are in-scope because they are the same
loop, asserted for a hostile input rather than a benign one.

- **Fail-closed on malformed invocation.** One scenario injects a malformed
  `RemoteEventHandlerInvocation` (missing scene, bad `event_kind`). Assert the
  Hub rejects it and **no handler fires** — `_hub_interaction_dispatch` returns
  early on missing `scene_id` (`clients.py:122-127`), unresolved element
  (`clients.py:131-138`), non-ABC element (`clients.py:145-151`), non-bool
  `value_changed` payload (`clients.py:161-167`), and unknown `event_kind`
  (`clients.py:180-187`). Deny by default; a bad message must not reach a
  handler.
- **Exactly-once as a security property.** I2's single-fire is not only
  correctness — a double-fire is a duplicated side effect (double publish,
  double state transition). The harness asserts `delivered == 1`, closing a
  replay/duplication gap at the boundary.
- **Connection-scoped isolation on the live loop.** Assert the business event
  lands **only** in the owning connection's inbox — a second subscribed
  connection receives nothing from the first's injected click. `hub.publish`
  fans out only within the caller's scope (`hub.py:95-105`). This extends
  `test_subscribe_publish.py:62-76` from a direct-publish assertion to the full
  interaction-driven loop.

## Deferred: visual + injection-fidelity proof

Two proofs are deferred until the screenshot capability (DES-028) is revisited,
and are **not** in current scope:

- **Visual paint.** A real GLFW/ImGui window painting the re-pushed replica.
- **Injection fidelity.** An independent check that a real GLFW click produces
  the **same** wire `RemoteEventHandlerInvocation` our `_emit_event` injection
  produces.

The one assumption this defers: that our `_emit_event` injection is faithful to
what a real GLFW/ImGui click emits. This is **true by construction today** — the
production click path and the injection both flow through the identical
`_emit_event` with the same `RemoteEventHandlerInvocation` shape
(`server.py:935-946`, `server.py:802-819`) — but it is not **independently
pinned** until DES-028 lands a real-window click test. When DES-028 is revisited,
a GPU-gated `@pytest.mark.e2e` variant can assert the real display's
handler-wrapping emits the identical invocation, closing this gap. Until then,
the in-process harness stands as the CI gate on the logic, and the fidelity
assumption is recorded here, not hidden.

## Write set (structure-driven)

The implementing specialist owns the exact module boundaries; the design fixes
the **shape**, not a predetermined edit list to existing files. Everything below
is test-tier plus one small test-facing addition on the Display.

- **New e2e-harness package** (e.g. `tests/e2e/`):
  - **in-process fixtures** — stand up the in-process Hub (`client_registry`,
    `hub_display`, `ensure_writer` subscriber), construct the `DisplayServer`
    logic with no window (per `test_display_rebind.py:50-53`), and wire the
    Display's outbound emit and the Hub's inbound dispatch across an
    `InMemoryConnection.paired()` duplex (per `test_text_outbound_e2e.py:46,82`),
    binding `RaisingRendererFactory` so any render call fails loud. Tear down
    through the shipped disconnect cascade so no scenario leaks subscriptions,
    writers, or `HubDisplay` roots.
  - **the simulated-agent driver** — exercises the real client/tool surface
    (`show`, `subscribe`, inject, `recv`/`drain_inbox`, `update`,
    `inspect_scene`) and drives the full bidirectional circle.
  - **the `Scenario` value class + scenario registry** (the declarative shape
    above), following the OO standard — data and behavior on the class, no
    module-level helpers operating on it.
  - **the bidirectional loop-invariant assertions** (I1–I6, including the I5
    return path) expressed once, parametrized over the scenario registry.
- **One test-facing Display addition** — the **addressable-injection**
  generalization: a method/hook on the Display (illustratively
  `inject(element_id, action, value)`) that builds the same
  `RemoteEventHandlerInvocation` `_auto_click_emit_loop` already builds and hands
  it to `_emit_event`. Not a protocol/wire message; a thin generalization of the
  existing test-mode loop.
- **Marker / pyramid slotting:** `@pytest.mark.integration` (Tier-2, **runs in
  CI**). Update [`tests/CLAUDE.md`](../../tests/CLAUDE.md) so the loop gate is
  named in the Round-trip procedure's Level 4.

The fixtures reuse the shipped `InMemoryConnection`, the real wire codec, the
production `DisplayServer` receive/wrap/emit logic, and `RaisingRendererFactory`
— all already GPU-free — so the harness adds no GPU dependency and duplicates no
rendering logic.

## Ratified design

The three decisions the prior draft left open are resolved:

1. **Process shape — in-process, no socket, no subprocess.** Resolved by
   operator ruling plus the existing code: `test_text_outbound_e2e.py` already
   drives the Hub↔Display boundary in one process through
   `InMemoryConnection.paired()`, and `test_display_rebind.py` already runs the
   `DisplayServer` receive/wrap logic with no window. The former GPU-layer split
   (headless peer vs ImGui subprocess) is dropped — there is one in-process
   harness.
2. **Interaction injection — addressable method on the Display, at
   `_emit_event`.** Resolved by operator ruling plus the existing
   `_auto_click_emit_loop`, which already emits real
   `RemoteEventHandlerInvocation`s at `_emit_event`. The harness generalizes it
   to target one element. No wire/control message; no ImGui; no fake path.
3. **GPU/pixel/fidelity layer — dropped from current scope.** Resolved by
   operator ruling: the visual paint and the independent real-click fidelity
   check are deferred to DES-028 (see
   [Deferred](#deferred-visual--injection-fidelity-proof)). The single deferred
   assumption — `_emit_event` injection faithfulness — is recorded, true by
   construction today, and pinned later.

Tier: `@pytest.mark.integration`, CI-capable. Implementation dispatches against
this document.
