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

## Element ABC: event-driven dispatch

Every io-model Element kind extends the same ABC. The ABC carries the
field plumbing introduced in PR 3 — `_renderer_factory`, `_emit`,
`render()`, the `_children()` hook, `apply_patch()` — and adds a typed
event-handler registry plus a dispatcher entry point that resolves which
handlers run for a given event.

### Handler registry API

```python
class Element(ABC):

    _renderer_factory: RendererFactory
    _emit: Emit
    _handlers: dict[type[Event], list[Handler[Event]]]

    def __new__(cls, *, renderer_factory: RendererFactory, emit: Emit) -> Self:
        self = super().__new__(cls)
        self._renderer_factory = renderer_factory
        self._emit = emit
        self._handlers = {}
        return self

    def add_handler[E: Event](
        self,
        event_type: type[E],
        handler: Handler[E],
    ) -> None:
        """Register a handler for an event type on this Element."""
        self._handlers.setdefault(event_type, []).append(handler)

    def remove_handler[E: Event](
        self,
        event_type: type[E],
        handler: Handler[E],
    ) -> None:
        """Deregister a handler. No-op if not registered."""
        registered = self._handlers.get(event_type)
        if registered is None:
            return
        try:
            registered.remove(handler)
        except ValueError:
            return
        if not registered:
            del self._handlers[event_type]

    def fire[E: Event](self, event: E) -> None:
        """Dispatch ``event`` to every handler registered for its type
        on this Element. Handlers are invoked in registration order
        against a snapshot of the list so a handler that mutates the
        registry does not affect the in-flight dispatch."""
        snapshot = tuple(self._handlers.get(type(event), ()))
        for handler in snapshot:
            handler(event)
```

`Handler[E]` is `Callable[[E], None]`. `Event` is the shared marker
Protocol for every dispatched event class — `ButtonClicked` satisfies
it, future kinds (`SliderChanged`, `TextEdited`) will satisfy it the
same way.

Three properties keep the API honest:

- The registry is per-Element. Handler lifetime is the Element's
  lifetime. When the Element is removed from the scene, its handlers go
  with it. No external cleanup needed.
- The registry is typed. `add_handler(ButtonClicked, handler)` expects
  `handler: Handler[ButtonClicked]`; passing a `Handler[SliderChanged]`
  is a type error at the call site, not a runtime surprise.
- Dispatch is snapshot-then-iterate. A handler may add or remove
  handlers without breaking the iteration that called it.

### Event class hierarchy

```python
class Event(Protocol):
    """Marker Protocol for events dispatched through Element.fire."""

@dataclass(frozen=True, slots=True)
class ButtonClicked:
    """A validated button click. Constructible ONLY by the Hub's
    interaction dispatcher (see the ButtonClicked validation section)."""
    scene_id: SceneId
    element_id: ElementId
    owner_id: ConnectionId
```

Events are frozen, slotted dataclasses with public fields — they are
inert value records that travel from the dispatcher to handlers. Their
construction sites are guarded (see the validation section); their
interior is read-only.

### Dispatcher loop

The Hub's `dispatch` entry point is the bridge between the wire layer
and the per-Element handler registries:

```python
async def dispatch(
    self,
    connection_id: ConnectionId,
    msg: InteractionMessage,
) -> None:
    """Resolve, validate, construct the typed event, fire handlers."""
    element = self._resolve(msg.scene_id, msg.element_id)
    event = self._display.interact(connection_id, msg, element)
    element.fire(event)
```

The dispatcher does three things in order:

1. **Resolve** — look up the Element by `(scene_id, element_id)` in the
   Hub's index. A missing Element raises before any side effect.
2. **Validate and construct** — `Display.interact` is the single
   construction site for the typed event (the canonical event class for
   buttons is `ButtonClicked`; future input kinds add their own typed
   event class and their own branch in `Display.interact`).
3. **Fire** — call `Element.fire(event)` to run every registered
   handler for the event's type.

The dispatcher does not know which handlers exist, what they do, or
whether any of them publishes a business event. The handler is the
policy; the dispatcher is the mechanism.

### Wire-to-handler decoding

Handlers are not authored by the agent in Python — the agent ships
declarative handler specifications on the wire as part of the scene
definition. Each Element kind defines a per-kind typed catalog of
handler factories; the decoder canonicalises the wire spec and calls
the matching factory to produce the `Handler[E]` callable, then calls
`add_handler(event_type, handler)` on the constructed Element.

The wire and catalog mechanics are the subject of the next section. The
boundary the Element ABC enforces is narrow: handlers arrive through
`add_handler`, dispatch happens through `fire`, and the registry is
inspectable for testing through the same two methods.

### Default behaviors are layered, not built in

The ABC does not provide default handlers. A button that does nothing
when clicked is a valid button — no implicit `on_click` is registered
by the ABC. Defaults that an agent expects (a dialog that dismisses on
its own Cancel button) are wired by the composite Element's own
construction-time logic, not by the ABC. The split keeps the ABC small
and the defaults discoverable: the only place that adds a handler is
either the agent's declarative spec or the component's own decoder.

### Why event-driven, not method-named

Two patterns were available for handler registration:

- Named method override on the Element — the spike's `on_click` shape.
- Typed event registry with `add_handler` / `remove_handler` — the
  pattern shipped here.

The event-registry pattern composes better. An Element can carry zero,
one, or many handlers for the same event type. A button can be both an
internal dialog-confirm controller and an emitter of a business event
on the same click. A test can register a probe handler without
subclassing the Element. The Element ABC stays small and the surface
the agent reasons about — events and handlers — stays uniform across
kinds.

The method-override pattern would have forced the ABC to grow per-event
hooks (`on_click`, `on_change`, `on_select`) and forced composites to
re-dispatch from their override to their listeners. The event registry
collapses both responsibilities into one piece of machinery, and the
catalog (described in the next section) makes the declarative use
ergonomic.

## Declarative handler catalog and wire format

Agents do not author handlers as Python code crossing the wire. Every
handler an Element runs is produced by a per-kind catalog of typed
factory methods that the Element class itself publishes. The agent
picks a catalog entry by name and supplies declarative parameters; the
decoder constructs the typed `Handler[E]` callable and registers it
through `add_handler`. No code travels from the agent to the Hub.

This mirrors how SwiftUI exposes environment-provided actions to
descendant views, how Vue resolves `@click="methodName"` against the
component's defined methods, and how JavaFX FXML's `onAction="#method"`
binds to the Controller's typed method at load time. The wire is data;
the catalog is the bounded vocabulary the wire may name.

### Per-Element catalog of handler factories

Each Element class publishes a catalog as a small typed namespace of
static factory methods. The factories are typed against the Element's
own event class — `ButtonHandlers`'s factories return
`Handler[ButtonClicked]`; a future `SliderHandlers` will return
`Handler[SliderChanged]`. The decoder routes wire factory specs to the
right catalog by the Element kind it is decoding for.

```python
class ButtonHandlers:
    """Catalog of declarative handler factories for ButtonElement."""

    @staticmethod
    def noop() -> Handler[ButtonClicked]:
        """Return a handler that does nothing.

        Used as the inner handler for clicks that exist only to fire
        decorator side effects (publish, log, etc.). A button that
        publishes a topic and does nothing else wraps ``noop()``.
        """
        def _handler(event: ButtonClicked) -> None:
            return None
        return _handler

    @staticmethod
    def call_model(method: str) -> Handler[ButtonClicked]:
        """Invoke a named method on the button's parent-component model.

        The parent-component model reference is set by the parent's
        decoder at construction time. The method name is the only wire
        parameter; the agent never sees the model object.
        """
        def _handler(event: ButtonClicked) -> None:
            event.button.owner_model.invoke(method)
        return _handler
```

`ButtonHandlers` is a namespace, not an instantiable class — every
member is a `@staticmethod` whose return type is the typed handler the
ABC expects. The decoder calls `ButtonHandlers.noop()` or
`ButtonHandlers.call_model("confirm")` based on the wire factory name
and parameters; the typed return propagates all the way to
`add_handler(ButtonClicked, handler)`.

### Decorators compose declaratively

Behavior that wraps any inner handler — publishing a business topic
after the inner runs, logging the event, throttling repeat firings —
is expressed as a decorator factory. Each decorator factory has the
same shape: `Callable[[Handler[E]], Handler[E]]`. Type-preserving in
the event class, so the chain remains type-safe end to end.

```python
def publish(topics: tuple[str, ...]) -> Callable[
    [Handler[ButtonClicked]],
    Handler[ButtonClicked],
]:
    """Wrap a handler so it publishes the listed topics after the inner runs."""
    def _decorator(inner: Handler[ButtonClicked]) -> Handler[ButtonClicked]:
        def _wrapped(event: ButtonClicked) -> None:
            inner(event)
            for topic in topics:
                _hub.publish(event.owner_id, topic, _payload_of(event))
        return _wrapped
    return _decorator
```

A single handler that opens a dialog AND publishes "work.saved" is
`publish(("work.saved",))(open_dialog_handler)`. Combinatorial cost
stays bounded: `N` factories times `M` decorators yields `N + M`
definitions, not `N * M`.

### Wire format — long form, then sugar

The long form is explicit and uniform: an event name, a factory name,
factory parameters, and an ordered list of decorator wrappers applied
inner-first.

```jsonc
{"event": "click",
 "factory": "noop",
 "wrap": [{"decorator": "publish", "topics": ["work.saved"]}]}
```

The decoder reads this verbatim: look up `"noop"` in `ButtonHandlers`,
call it with no params, then apply each entry in `"wrap"` outermost
last (so the first listed decorator sees the agent's inner handler,
each subsequent decorator wraps the prior result). The final
`Handler[ButtonClicked]` lands on the Element via `add_handler`.

The common case — fire a business topic with nothing else attached —
gets a sugar shorthand the decoder canonicalises to the long form
before constructing the chain:

```jsonc
{"event": "click", "publish": ["work.saved"]}
```

After canonicalisation, both wire shapes produce the same long-form
record:

```jsonc
{"event": "click",
 "factory": "noop",
 "wrap": [{"decorator": "publish", "topics": ["work.saved"]}]}
```

Sugar is one canonical rewrite per recognised key (`publish`, future
`call_model`, etc.). The long form remains the authority — every wire
spec is canonicalised first, then dispatched to the catalog and
decorator chain through a single code path.

### Per-parent-component verb vocabularies

A `Button` inside a `Dialog` and a `Button` inside a `Form` share the
same Element kind but answer to different verbs. Each composite Element
publishes a typed action mapping — the verbs its child controllers may
invoke against its model:

```python
class DialogModel:
    """Component-local model that exposes a typed verb mapping."""

    _ACTIONS: ClassVar[Mapping[str, Callable[["DialogModel"], None]]] = {
        "confirm": lambda self: self.confirm(),
        "cancel":  lambda self: self.cancel(),
        "close":   lambda self: self.close(),
        "dismiss": lambda self: self.cancel(),  # alias
    }

    def invoke(self, action: str) -> None:
        action_fn = self._ACTIONS.get(action)
        if action_fn is None:
            raise ValueError(
                f"unknown dialog action: {action!r} "
                f"(expected one of {sorted(self._ACTIONS)})"
            )
        action_fn(self)
```

A future `FormModel` publishes its own vocabulary — `submit`, `reset`,
`validate` — through the same `_ACTIONS` shape.

When the decoder processes a child `Button` whose wire spec carries
`{event: "click", factory: "call_model", method: "confirm"}`, it looks
up `"confirm"` in the parent component's published verb mapping at
decode time. An unrecognised verb fails loudly at decode, not at click.
Mirrors SwiftUI's `@Environment`-provided actions, Vue's
provide/inject, and JavaFX FXML's load-time controller binding.

### No `getattr`, no `hasattr` — typed mappings throughout

The catalog and the verb mappings replace every introspection-based
dispatch the spike used. The decoder looks up a factory name in a
`Mapping[str, Callable[..., Handler[E]]]`; the verb dispatcher looks
up a verb name in `Mapping[str, Callable[[Model], None]]`; the ABC's
`add_handler` takes a typed `event_type` and a typed `handler`.
`isinstance` is the only runtime type check the dispatcher performs,
and it runs against published Protocols and concrete event classes.

This matters because the wire is the agent's surface. Every name the
agent may use is enumerated in the Element kind's catalog and its
parent composite's verb mapping. If the name is unknown, the decoder
fails before any handler is registered. The Hub never executes wire
content as Python; the only Python that runs in response to a click is
a factory the Element kind itself ships, possibly wrapped by decorators
the Hub itself ships.

### Inline-code escape hatch is out of scope

A future kind of catalog entry — `{factory: "inline", source: "..."}`
— is forward-compatible with this shape. The agent ships a Python
expression; the decoder constructs an inline handler from it; the
decorator chain wraps it the same way. That capability is not in PR 4
scope. The catalog model is built to accept it without restructuring
when the trust model for executing agent-authored code is ready.
