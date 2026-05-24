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
    _removed: bool
    _observers: list[Callable[[str], None]]

    def __new__(cls, *, renderer_factory: RendererFactory, emit: Emit) -> Self:
        self = super().__new__(cls)
        self._renderer_factory = renderer_factory
        self._emit = emit
        self._handlers = {}
        self._removed = False
        self._observers = []
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

    def add_observer(self, observer: Callable[[str], None]) -> None:
        """Register a property-change observer. Used by parent
        composites to react to children flipping ``_removed`` (and,
        in future, ``_visible`` / ``_enabled``)."""
        self._observers.append(observer)

    @property
    def removed(self) -> bool:
        return self._removed

    def _mark_removed(self) -> None:
        """Flip ``_removed`` and notify observers. Idempotent — a second
        call is a no-op. This is the single mechanism for marking any
        Element removed; the three removal paths (agent ``RemoveElement``,
        component self-dismiss, connection disconnect) all reach it."""
        if self._removed:
            return
        self._removed = True
        for observer in tuple(self._observers):
            observer("removed")
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
    def call_model(bound_method: Callable[[], None]) -> Handler[ButtonClicked]:
        """Invoke a parent-component model method bound at decode time.

        The parent component's decoder (e.g., ``JsonDialogDecoder``)
        resolves the verb string from the wire (e.g., ``"confirm"``)
        against the parent model's typed ``_ACTIONS`` mapping and passes
        the resolved bound method into this factory. The handler closure
        captures the binding; the event itself carries no model reference.
        """
        def _handler(_event: ButtonClicked) -> None:
            bound_method()
        return _handler
```

`ButtonHandlers` is a namespace, not an instantiable class — every
member is a `@staticmethod` whose return type is the typed handler the
ABC expects. The decoder calls `ButtonHandlers.noop()` or
`ButtonHandlers.call_model(model.confirm)` based on the wire factory
name and parameters — the verb string `"confirm"` is resolved against
the parent model's `_ACTIONS` mapping by the parent's decoder, and the
resolved bound method is passed in. The typed return propagates all
the way to `add_handler(ButtonClicked, handler)`.

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

## Composite Elements as MVC components

A `DialogElement` is more than a panel with buttons inside. It is a
self-contained component with its own model, its own view, and its own
controllers — the classic Model-View-Controller split, contained within
a single Element kind. Future composites (`FormElement`, `WizardElement`,
the inspector, the workspace) follow the same pattern. The component
is the unit of encapsulation; nothing outside the component touches its
model.

The component embodies the boundary the io-model needs: when an agent
defines a Dialog with Confirm and Cancel buttons, the agent declares
what each button means in the Dialog's vocabulary — and that's the end
of the agent's involvement in the Dialog's behavior. The component
wires its own controllers, dispatches its own state changes, and
notifies its parent through the Element Observer subsystem when its
visible state changes.

### Model — the component's private state

`DialogModel` is the Dialog's internal state. It holds the properties
the Dialog cares about and the methods that mutate them. The model is
an implementation detail of the `DialogElement` component — no code
outside the component constructs it directly, references it by name,
or invokes its methods through any path other than the typed verb
mapping the model itself exposes.

```python
class DialogModel:
    """The Dialog's private state. Owned by DialogElement.

    Holds only the Dialog-specific properties (``_visible``,
    ``_confirmed``). The ``_removed`` flag and observer cascade live on
    the Element ABC — confirm/cancel/close set the model's own state,
    then invoke the ``_on_dismiss`` callback the DialogElement
    installed at construction. That callback calls
    ``Element._mark_removed`` on the owning Element, which is the one
    place ``_removed`` is set and the one place observers fire."""

    _ACTIONS: ClassVar[Mapping[str, Callable[["DialogModel"], None]]] = {
        "confirm": lambda self: self.confirm(),
        "cancel":  lambda self: self.cancel(),
        "close":   lambda self: self.close(),
        "dismiss": lambda self: self.cancel(),
    }

    _visible: bool
    _confirmed: bool
    _on_dismiss: Callable[[], None]

    def __new__(cls, *, on_dismiss: Callable[[], None]) -> Self:
        self = super().__new__(cls)
        self._visible = True
        self._confirmed = False
        self._on_dismiss = on_dismiss
        return self

    def confirm(self) -> None:
        """Record confirmation and dismiss the dialog."""
        self._confirmed = True
        self._dismiss()

    def cancel(self) -> None:
        """Dismiss the dialog without recording confirmation."""
        self._dismiss()

    def close(self) -> None:
        """Dismiss the dialog (semantic alias for an unspecified close)."""
        self._dismiss()

    def invoke(self, action: str) -> None:
        """Dispatch a verb name from the typed action mapping."""
        action_fn = self._ACTIONS.get(action)
        if action_fn is None:
            raise ValueError(
                f"unknown dialog action: {action!r} "
                f"(expected one of {sorted(self._ACTIONS)})"
            )
        action_fn(self)

    def _dismiss(self) -> None:
        """Drop visibility and ask the owning Element to mark itself
        removed. Idempotency lives on ``Element._mark_removed`` — a
        second dismiss is a harmless no-op there."""
        self._visible = False
        self._on_dismiss()
```

`_ACTIONS` is the typed mapping the wire-level verb vocabulary
resolves against (introduced in the catalog section). The model
exposes no observer hook of its own — the Element Observer hook the
Dialog's parent composite registers through lives on the Element
ABC (`Element.add_observer`), and the model reaches it indirectly by
invoking `_on_dismiss`, which the decoder bound to the owning
`DialogElement._mark_removed`.

### View — DialogElement reads model state to render

`DialogElement` is the Element kind. Its render path reads the model;
it does not write the model. The view is a function of state.

```python
class DialogElement(Element):
    """A composite Element whose state is owned by DialogModel."""

    _id: ElementId
    _model: DialogModel
    _children_tuple: tuple[Element, ...]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory,
        emit: Emit,
        id: ElementId,
    ) -> Self:
        self = super().__new__(cls, renderer_factory=renderer_factory, emit=emit)
        self._id = id
        self._children_tuple = ()
        return self

    @property
    def id(self) -> ElementId:
        return self._id

    @property
    def visible(self) -> bool:
        return self._model._visible

    def _children(self) -> tuple[Element, ...]:
        return self._children_tuple

    def _install_model(self, model: DialogModel) -> None:
        """Decoder-only seam: install the model once it is constructed
        with ``on_dismiss=self._mark_removed`` bound."""
        self._model = model

    def _install_children(self, children: tuple[Element, ...]) -> None:
        """Decoder-only seam: install children after the model exists,
        so child Buttons can bind to it."""
        self._children_tuple = children
```

The Dialog exposes `visible` as a read-only property backed by the
model. The `removed` property is inherited from the Element ABC and
reflects the single Element-level `_removed` flag — every removal
path (agent `RemoveElement`, the component's own dismiss, connection
disconnect) flips that one flag through `Element._mark_removed`.

### Controllers — child Buttons reference the model

Each child Button in the Dialog is a controller for one of the model's
actions. The wire spec the agent ships says only "this button's click
means 'confirm'"; the decoder wires the Button to the Dialog's model
through the bound-callback pattern.

```python
class JsonDialogDecoder:
    """Decoder for DialogElement wire payloads."""

    def decode(self, raw: Mapping[str, object]) -> DialogElement:
        # 1. Construct the Dialog element first so its `_mark_removed`
        #    method exists to be bound into the model's `on_dismiss`.
        dialog = DialogElement(
            renderer_factory=self._renderer_factory,
            emit=self._emit,
            id=ElementId(self._require_string(raw, "id")),
        )

        # 2. Construct the model with its dismiss callback bound to the
        #    Dialog's Element-level `_mark_removed`. Confirm/cancel/close
        #    on the model now route through the one Element-level
        #    `_removed` flag and the one Element-level observer cascade.
        model = DialogModel(on_dismiss=dialog._mark_removed)
        dialog._install_model(model)

        # 3. Decode each child Button. The Button's click-handler factory
        #    is ButtonHandlers.call_model, with the verb name as its only
        #    wire parameter. The factory closes over the model the decoder
        #    has just constructed.
        children = tuple(
            self._button_decoder.decode_for_parent(child_raw, owner_model=model)
            for child_raw in self._require_children(raw)
        )

        # 4. Install the wired children.
        dialog._install_children(children)
        return dialog
```

The Button's decoder receives `owner_model=model` and uses it when it
builds the typed `Handler[ButtonClicked]` from the `call_model` factory
in the catalog. By the time the Dialog is returned from `decode`, every
child Button's click handler already holds a reference to the right
model and the right verb. No runtime late-binding, no string lookup
against `getattr`. The wire defines the verb; the decoder resolves it.

This is the same shape as JavaFX FXML's controller binding: at load
time the FXML parser resolves `onAction="#confirm"` against the
Controller's `@FXML` methods. Loud at load, silent and typed at run.

### Element Observer — intra-Hub property propagation

When the user clicks Confirm, the controller runs
`model.invoke("confirm")`, which calls `self.confirm()` on the model,
which sets `_confirmed = True` and invokes `_on_dismiss`. The dismiss
callback is `dialog._mark_removed` — the Element-ABC method that
flips `_removed = True` on the DialogElement itself and notifies the
Element's observers. The Dialog's parent composite is one of those
observers. On `"removed"`, the parent performs the same drop an
agent-issued `RemoveElement` would: it prunes the Dialog out of its
own children tuple AND calls `HubDisplay.apply(RemoveElement(...))`
so the Hub's `(scene_id, element_id)` index drops the entry too.
Skipping either half leaves the system inconsistent — local-only
pruning leaks an orphan in the Hub index that still resolves to a
tree the parent no longer holds; Hub-only removal leaves a dangling
reference in the parent's children tuple.

```python
class PanelElement(Element):
    """A composite that observes its children's removal."""

    def _install_children(self, children: tuple[Element, ...]) -> None:
        for child in children:
            child.add_observer(
                lambda prop, _c=child: self._on_child_property(prop, _c)
            )
        self._children_tuple = children

    def _on_child_property(self, prop: str, child: Element) -> None:
        if prop == "removed":
            # 1. Local prune from this parent's children tuple.
            self._children_tuple = tuple(
                c for c in self._children_tuple if c is not child
            )
            # 2. Hub-side drop — same operation an agent-issued
            #    RemoveElement would invoke. Keeps the (scene_id,
            #    element_id) index consistent with the local view.
            self._hub_display.apply(
                self._owner_connection_id,
                RemoveElement(scene_id=self._scene_id, element_id=child.id),
            )
```

This is the Element Observer subsystem in action: a property on one
Element changes, an observer registered by the parent runs, and the
parent updates its own state — both its own children tuple and the
Hub's authoritative index. Standard Swing/Cocoa/Qt mechanics, with
the extra discipline that the Hub index is part of the parent's
"state" for cascade purposes. The `add_observer` hook lives on the
Element ABC, so every Element kind exposes it identically; `visible`
and `enabled` will propagate the same way in future Layout work
(without the Hub-index call — only `removed` mutates the index).

The same machinery handles connection teardown: when a connection
disconnects, the Hub calls `_mark_removed` on every root Element the
connection owns. The Element-level notifications cascade up to each
parent's observer; parents prune both halves; the scene shrinks
naturally and the Hub index shrinks with it. All three removal paths
— agent `RemoveElement`, component self-dismiss, connection
disconnect — flip the same Element-level `_removed` flag through the
same `_mark_removed` method and fire the same observer cascade.

### Element Observer is not Agent Subscribe

The Element Observer subsystem and the Agent Subscribe / Publish
subsystem are two different mechanisms with two different lifecycles.
They share no machinery. The Element Observer is in-process,
property-typed, and registered by parents on their direct children.
The Agent Subscribe registry is connection-scoped, topic-named, and
serves cross-process pub/sub for agents and applets.

| Concern | Element Observer | Agent Subscribe |
|---|---|---|
| Scope | Intra-Hub, intra-component | Cross-process |
| Key | Property name on an Element | Topic name in a connection's scope |
| Registration | Parent registers on child | Connection subscribes to its own scope |
| Cleanup | Element death drops observers | Connection disconnect drops the scope |
| Wire involvement | None — process-local references | Outbound `ObserverMessage` over the wire |
| Trust model | None — every observer is in-process | Per-connection scoping (covered later) |

A DialogElement's self-dismiss is intra-component coordination: the
controller mutates the model, the model notifies the observer, the
observer prunes. No topic name is invented; no pub-sub message crosses
a process boundary. Pub-sub is reserved for cross-component business
events — "work.saved", "scene.dismissed-by-agent" — where the producer
and the consumer live in different connections, different processes,
or different machines.

Conflating the two subsystems is the easy mistake. The discipline that
prevents it is one rule: intra-component coordination is Observer;
cross-component / cross-process is Pub-Sub. If a DialogElement
publishes a topic, the topic is a business event for outside
consumers, not the means by which the Dialog dismisses itself.

### The bound-callback pattern at the boundary

The agent's declaration is small and declarative:

```jsonc
{
  "kind": "dialog",
  "id": "save_confirm",
  "children": [
    {"kind": "button", "id": "ok",     "label": "OK",
     "on": [{"event": "click", "factory": "call_model", "method": "confirm"}]},
    {"kind": "button", "id": "cancel", "label": "Cancel",
     "on": [{"event": "click", "factory": "call_model", "method": "cancel"}]}
  ]
}
```

The agent says "this button means confirm." It does not say "when this
button is clicked, mark the Dialog's model `_confirmed = True` and
notify the Dialog's parent through the Observer." That sentence is the
component's documented behavior, expressed once in the Dialog's
`DialogModel.confirm` method, resolved at decode time against the
Dialog's typed verb mapping, and bound into each child Button's
typed handler.

By the time the user clicks, every reference is resolved, every type
is checked, every dispatch is a method call on an object the decoder
constructed. The wire is data. The component is code. The decoder is
the seam.

Future composite Elements follow the same template: a private model
that publishes a typed verb mapping, a view-side Element class that
reads model state, a controller-side decoder that constructs the model
first and then wires every child controller's typed handler against
it. Form, Wizard, Inspector, Workspace — each its own component, each
its own model, each its own verb vocabulary, all reading and writing
through the same MVC seam.

## ButtonClicked: one event, one validation boundary

`ButtonClicked` is the canonical typed event for a validated button
press. It has exactly one constructor — the Hub's `Display.interact`
method — and exactly one validation site — the same method. Everything
upstream of `Display.interact` is wire-side triage; everything
downstream is typed handler dispatch. There is no intermediate class
between the inbound `InteractionMessage` and the `ButtonClicked` the
dispatcher hands to `Element.fire`.

### The event class

```python
@dataclass(frozen=True, slots=True)
class ButtonClicked:
    """A validated button click. Constructible ONLY by Display.interact."""

    scene_id: SceneId
    element_id: ElementId
    owner_id: ConnectionId
    kind: ClassVar[Literal["button_clicked"]] = "button_clicked"

    def __new__(
        cls,
        *,
        scene_id: SceneId,
        element_id: ElementId,
        owner_id: ConnectionId,
        _token: object,
    ) -> Self:
        if _token is not Display._construction_token:
            msg = (
                "ButtonClicked must be constructed by Display.interact; "
                "direct construction is not allowed"
            )
            raise TypeError(msg)
        self = super().__new__(cls)
        return self
```

The factory guard is the PY-CC-3 pattern: the class refuses any
construction path that does not present the token the `Display` class
holds. Tests that need a `ButtonClicked` get one by calling
`Display.interact` with a valid `InteractionMessage`, not by
constructing the event directly. The token is module-private to the
Hub; no other module can forge it.

The class is frozen and slotted — once constructed, it is an inert
record of three values plus a `kind` discriminator. Handlers read
fields; they do not mutate the event.

### The validation site

`Display.interact` is the single function that turns a wire
`InteractionMessage` into a typed `ButtonClicked`. Every domain check
that the click is valid happens here, exactly once.

```python
class Display:
    """Validation site and dispatch entry point. The Element index
    lives on HubDisplay; Display borrows it through a constructor
    dependency rather than maintaining a parallel copy."""

    _construction_token: ClassVar[object] = object()

    def __init__(self, hub_display: HubDisplay) -> None:
        self._hub_display = hub_display

    def interact(
        self,
        client_id: ConnectionId,
        msg: InteractionMessage,
    ) -> ButtonClicked:
        """Validate the wire message, construct the typed event, return it.

        Raises on any validation failure — the caller (the pump) has already
        done wire-side triage, so anything reaching this method is either
        a valid click or a domain-level bug. Validation failures are not
        normal outcomes; they are errors that surface immediately.
        """
        scene_id = msg.require_scene_id()
        element_id = ElementId(msg.element_id)

        if client_id not in self._clients:
            raise UnknownClientError(client_id=client_id)
        element = self._hub_display.resolve(scene_id, element_id)
        if element.kind != "button":
            raise WrongKindError(
                scene_id=scene_id,
                element_id=element_id,
                expected="button",
                got=element.kind,
            )

        return ButtonClicked(
            scene_id=scene_id,
            element_id=element_id,
            owner_id=client_id,
            _token=Display._construction_token,
        )
```

The method does three things in order: validate the client exists, ask
`HubDisplay` to resolve `(scene_id, element_id)` to an `Element` (which
raises `UnknownSceneError` or `UnknownElementError` on miss), validate
the element is the right kind for the action. On success it constructs
the typed event and returns it. On failure it raises a typed domain
error. There is no `None` return, no boolean success flag, no error
sentinel — either the caller gets a typed event or the call raises.

`HubDisplay` is the single authoritative index of Elements by
`(scene_id, element_id)`. `Display` does not maintain its own
`_scenes` dict; that would be a parallel index, exactly the kind of
duplication the guiding principle rules out. `Display` takes
`HubDisplay` as a constructor dependency and reads through it for
every validation lookup. One index, one owner, every consumer goes
through the same surface.

### The pump shrinks to wire-side triage

The component that translates raw wire frames into Hub calls — the
domain pump — now does only wire-shape filtering. Its previous
responsibility for intermediate-class construction and partial domain
reasoning is gone.

```python
class WirePump:
    """Wire-side triage. Drops malformed or non-element messages, then
    hands the surviving message directly to Display.interact."""

    _NON_ELEMENT_ACTIONS: ClassVar[frozenset[str]] = frozenset(
        {"menu", "frame_close"},
    )

    def route_interaction(
        self,
        client_id: ConnectionId,
        msg: InteractionMessage,
    ) -> None:
        if msg.action in self._NON_ELEMENT_ACTIONS:
            return
        if msg.scene_id is None:
            return
        if msg.value is not True:
            return

        event = self._display.interact(client_id, msg)
        element = self._hub_display.resolve(event.scene_id, event.element_id)
        element.fire(event)
```

Three wire-shape filters, then the message goes to `Display.interact`,
then the typed event goes to `Element.fire`. The pump does no domain
reasoning, no element resolution, no kind check, no ownership check.
Those live in `Display.interact` (validation) and `HubDisplay.resolve`
(index lookup) — the same `HubDisplay` instance `Display` borrows for
its own validation. The pump's post-validation re-resolution uses the
same authority, not a parallel one.

### One validation site, no defense-in-depth

`Display.interact` is the only place a `ButtonClicked` is constructed
and the only place that validates the inputs that go into it. There is
no second validation layer in `Element.fire`, no third one in handler
factories, no fourth one in the catalog. The class's factory guard
ensures no caller bypasses `Display.interact` to manufacture a synthetic
event; the validation gate is therefore the construction gate.

Defense-in-depth across multiple validation sites was an artifact of
the prior arrangement where the wire-side intermediate class and the
domain-side event both held overlapping field sets and each had to be
re-checked when crossing the boundary. With a single class constructed
at a single site, the two checks collapse into the one check that
matters.

The `ButtonPressed` class is deleted. The `Interaction` sum type and
its `domain/interaction.py` module are deleted. The
`_warn_on_error(...)` helper in the pump is deleted. Every legacy
caller migrates in the same PR — there is no `ButtonPressed` import
that survives, no `Interaction` reference that lingers, no parallel
old-and-new code path.

### Future input kinds extend the same dispatch

The `Display.interact` method's structure scales to additional input
kinds without re-introducing a sum type. Each new input kind adds a
branch that matches on the Element's `kind` plus the wire `value`'s
shape, runs its own typed validation, and constructs its own typed
validated event. The discriminator is the resolved Element kind plus
the value shape, not the `msg.action` string — `action` carries the
agent-supplied action name (`elem.action or elem.id` for buttons),
which varies per element and cannot be a fixed verb. A button click
is `kind == "button" and value is True`; a slider change is
`kind == "slider" and isinstance(value, float)`; future input kinds
follow the same `kind + value-shape` pattern.

```python
class Display:

    def interact(
        self,
        client_id: ConnectionId,
        msg: InteractionMessage,
    ) -> Event:
        # Resolve the Element first — every input kind needs it.
        scene_id = msg.require_scene_id()
        element_id = ElementId(msg.element_id)
        self._require_known_client(client_id)
        element = self._hub_display.resolve(scene_id, element_id)

        if element.kind == "button" and msg.value is True:
            return ButtonClicked(
                scene_id=scene_id,
                element_id=element_id,
                owner_id=client_id,
                _token=Display._construction_token,
            )
        if element.kind == "slider" and isinstance(msg.value, float):
            return SliderChanged(
                scene_id=scene_id,
                element_id=element_id,
                owner_id=client_id,
                new_value=msg.value,
                _token=Display._construction_token,
            )
        # … future input kinds add their own typed branch here.

        raise UnsupportedInteractionError(
            action=msg.action, kind=element.kind,
        )
```

`SliderChanged`, `TextEdited`, `CheckboxToggled` — each is its own
frozen typed class with its own factory guard, constructed by
`Display.interact` and dispatched through `Element.fire` against
handlers registered for its specific type. No intermediate-class sum
type ever resurfaces. The catalog (`SliderHandlers`, `TextHandlers`,
etc.) registers typed factories against the typed event class, the
same way `ButtonHandlers` registers against `ButtonClicked`.

The structure of the validation method grows by one branch per kind.
The structure of the dispatcher and the handler registry does not
change at all.

## Agent Subscribe and Publish

The Agent Subscribe / Publish subsystem is the cross-process pub-sub
mechanism the Hub offers to agents and applets. A connection registers
interest in a topic; another call on the same connection publishes a
payload to that topic; subscribers receive the payload as a typed
outbound `ObserverMessage` over their wire.

This subsystem is entirely separate from the Element Observer subsystem
described earlier. The Element Observer is intra-Hub, in-process,
property-typed, and registered by parent composites on their direct
children. The Agent Subscribe registry is cross-process, topic-named,
and lives at the boundary where the Hub talks to remote connections.
The two share no machinery, no data structures, no lifecycle. Intra-
component coordination uses the Observer; cross-component and cross-
process business events use Subscribe and Publish.

### The subscription registry

```python
class SubscriptionRegistry:
    """Per-connection topic registry. Snapshot-then-iterate for publish."""

    _by_connection: dict[ConnectionId, dict[Topic, set[Handler]]]
    _lock: threading.Lock

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._by_connection = {}
        self._lock = threading.Lock()
        return self

    def subscribe(
        self,
        connection_id: ConnectionId,
        topic: Topic,
        handler: Handler,
    ) -> None:
        with self._lock:
            scope = self._by_connection.setdefault(connection_id, {})
            scope.setdefault(topic, set()).add(handler)

    def unsubscribe(
        self,
        connection_id: ConnectionId,
        topic: Topic,
        handler: Handler,
    ) -> None:
        with self._lock:
            scope = self._by_connection.get(connection_id)
            if scope is None:
                return
            handlers = scope.get(topic)
            if handlers is None:
                return
            handlers.discard(handler)
            if not handlers:
                del scope[topic]

    def snapshot_subscribers(
        self,
        connection_id: ConnectionId,
        topic: Topic,
    ) -> tuple[Handler, ...]:
        with self._lock:
            scope = self._by_connection.get(connection_id, {})
            return tuple(scope.get(topic, ()))

    def drop_connection(self, connection_id: ConnectionId) -> None:
        with self._lock:
            self._by_connection.pop(connection_id, None)
```

The outer key is `ConnectionId`. The inner key is `Topic`. The value is
a set of handlers — typically a one-element set holding the outbound-
message writer for the subscribing connection itself. The shape
`dict[ConnectionId, dict[Topic, set[Handler]]]` makes per-connection
scoping a property of the data structure: cleanup of a disconnected
connection is one `dict.pop`, and no topic registration leaks across
connections by construction.

### The Hub's subscribe, unsubscribe, and publish

The Hub exposes three operations, all of them connection-scoped:

```python
class Hub:

    def subscribe(
        self,
        connection_id: ConnectionId,
        topic: Topic,
    ) -> None:
        """Register the caller's connection for ``topic``.

        Declaration is implicit — calling subscribe with a topic the
        connection has not used before adds it to the connection's scope.
        """
        handler = self._writer_for(connection_id)
        self._subscriptions.subscribe(connection_id, topic, handler)

    def unsubscribe(
        self,
        connection_id: ConnectionId,
        topic: Topic,
    ) -> None:
        """Drop the caller's subscription to ``topic``. No-op if absent."""
        handler = self._writer_for(connection_id)
        self._subscriptions.unsubscribe(connection_id, topic, handler)

    def publish(
        self,
        connection_id: ConnectionId,
        topic: Topic,
        payload: Mapping[str, object],
    ) -> int:
        """Fan ``payload`` out to ``topic``'s subscribers in the caller's scope.

        Returns the number of subscribers that received the message.
        Subscribers are snapshotted under a short lock, then iterated
        outside the lock to avoid serializing publishes against each
        other and against subscribe / unsubscribe.
        """
        message = ObserverMessage(topic=topic, payload=payload)
        subscribers = self._subscriptions.snapshot_subscribers(
            connection_id, topic,
        )
        for handler in subscribers:
            handler(message)
        return len(subscribers)
```

The three operations share one rule: every call is scoped to the
`connection_id` of the caller. A subscription registered by connection
A is visible only to connection A. A publish issued by connection A is
delivered only to subscribers within connection A's own scope.

### Per-connection topic scoping

A connection can subscribe and publish only within its own scope. The
trust model is the simplest possible: no connection can see, subscribe
to, or publish into another connection's topics. Topic name collisions
across connections do not matter — connection A's `work.saved` and
connection B's `work.saved` are different scopes, holding different
subscriber sets, fanning out different payloads.

Declaration is implicit. There is no separate `declare_topic` step. The
first `subscribe` or `publish` for a topic name within a connection's
scope is the declaration. Subsequent calls on the same name add to the
existing scope.

Cross-connection pub-sub is not possible in PR 4. A future capability
that allows agent-to-agent or applet-to-applet topic sharing would be
a new feature with its own access-control rule, not a fix to the
per-connection trust model. The mechanism for cross-connection pub-sub
is genuinely absent: there is no path through the registry, the Hub
methods, or the wire format that could deliver one connection's
publish to another connection's subscriber.

### The ObserverMessage wire kind

When `Hub.publish` fans a payload out to a connection's subscribers,
each subscriber receives the payload as a typed `ObserverMessage` on
its outbound wire.

```python
@dataclass(frozen=True, slots=True)
class ObserverMessage:
    """Outbound wire kind delivered to a connection on its subscribed topics."""

    topic: Topic
    payload: Mapping[str, object]
    kind: ClassVar[Literal["observer"]] = "observer"

    def to_wire(self) -> Mapping[str, object]:
        return {
            "kind": self.kind,
            "topic": self.topic,
            "payload": self.payload,
        }

    @classmethod
    def from_wire(cls, raw: Mapping[str, object]) -> Self:
        ...
```

A concrete wire frame looks like this:

```jsonc
{
  "kind": "observer",
  "topic": "work.saved",
  "payload": {"element_id": "save_btn", "ts": "2026-05-24T17:00:00Z"}
}
```

`ObserverMessage` joins the existing `MessageRegistry` alongside
`InteractionMessage`, `SceneMessage`, and the lifecycle kinds. The
registry maps `kind` strings to typed message classes; the decoder
dispatches on `kind`; encoders serialize via `to_wire`. No agent code
ever constructs `ObserverMessage` directly — the Hub constructs the
message inside `publish` and hands the writer the typed value.

`InteractionMessage` is not reused for the outbound direction.
`InteractionMessage` is by name and by content an inbound message —
display tier or agent tier sending an event into the Hub. Reusing the
same class for outbound delivery would collapse two unrelated concepts
under one name and force every wire reader to disambiguate direction
from context. `ObserverMessage` is its own type, with its own
serialization, its own decoder, and its own dispatch path.

### Concurrency: snapshot-then-iterate

The registry's lock is held only long enough to mutate the data
structure or copy a subscriber set. The publish fan-out iterates the
snapshot outside the lock.

```python
def publish(
    self,
    connection_id: ConnectionId,
    topic: Topic,
    payload: Mapping[str, object],
) -> int:
    message = ObserverMessage(topic=topic, payload=payload)
    subscribers = self._subscriptions.snapshot_subscribers(
        connection_id, topic,
    )            # short lock: copy the set, release.
    for handler in subscribers:
        handler(message)   # iterates outside the lock.
    return len(subscribers)
```

The alternative — holding the lock across the entire publish-and-send
loop — serializes publishes against each other and against
subscribe / unsubscribe. A slow subscriber stalls every other publish
on every other topic. Snapshot-then-iterate eliminates that coupling:
two concurrent publishes on different topics never wait for each
other, and a subscriber added in the middle of a publish cycle simply
joins the next snapshot.

The price is that a subscriber removed mid-publish may still receive
one final message — the snapshot was taken before the removal. This is
the same well-understood eventual-consistency behavior every snapshot-
based observer pattern carries; subscribers that need stricter
delivery semantics gate on the topic from inside the handler.

### Cleanup on disconnect

When a connection closes — whether the MCP session ends, the TCP
applet hangs up, or the Hub forcibly evicts the connection — the
registry drops the entire inner dict for that `ConnectionId`:

```python
class Hub:

    def on_disconnect(self, connection_id: ConnectionId) -> None:
        self._subscriptions.drop_connection(connection_id)
```

One `dict.pop` removes every topic and every handler that the
connection registered. There is no per-topic cleanup walk, no handler
reference list to scan, no global registry to update. The
per-connection outer key was chosen precisely so that disconnect
cleanup is `O(1)` against the data structure, not `O(number of
topics)` or `O(number of handlers)`.

## Lifecycle

Two registries hold state that outlives a single interaction: the
per-Element handler registry (on every Element instance) and the
per-connection subscription registry (on the Hub). They are
lifecycle-independent. Each owns its own cleanup path; neither calls
into the other.

The correctness argument for the design rests on this independence. A
handler that fires after the subscriber it would have notified is gone
has no observable effect — the publish it makes goes into an empty
subscriber snapshot and the call returns zero. An Element handler that
references a model the model's component owns dies when the component
dies; the Element's `_handlers` dict goes out of scope with the
Element. Neither path leaks state past its owner's lifetime.

### Element handlers die with the Element

Handlers live on Element instances. The handler registry is a field on
the `Element` ABC — `_handlers: dict[type[Event], list[Handler[Event]]]`
— populated by the decoder at construction time. When the Element is
removed from a scene, its `_handlers` dict is dropped along with every
other field on the instance.

Removal of an Element happens through one of three paths, all of which
end up at the same place:

- An agent issues a `RemoveElement` update. The Hub looks up the
  Element, removes it from the scene's index, and drops the only
  reference the Hub holds. The Element becomes garbage.
- A component dismisses itself. The component's model calls back
  into the owning Element's `_mark_removed`, which flips the
  Element-level `_removed = True` and notifies the Element's
  observers. The parent composite is one of those observers and
  performs the same drop: it prunes the component from its own
  children tuple AND calls
  `HubDisplay.apply(connection_id, RemoveElement(scene_id, child_id))`
  to clear the Hub's `(scene_id, element_id)` index entry. Both
  operations are required — local pruning alone leaves an orphan
  index entry that still resolves to a tree the parent no longer
  holds.
- A connection disconnects. The Hub iterates every Element the
  disconnecting connection owns and calls `_mark_removed` on each
  root, which flips Element-level `_removed = True` and fires the
  observer cascade. Each parent's observer prunes its own children
  tuple and calls `HubDisplay.apply(...RemoveElement...)`.

In all three paths, the handler registry follows the Element. No
external bookkeeping tracks handlers separately. No registry needs to
be updated when an Element disappears.

### Subscriptions die with the connection

Subscriptions live in the Hub's `SubscriptionRegistry`, keyed by
`ConnectionId` at the outer level. When a connection disconnects, the
Hub calls `SubscriptionRegistry.drop_connection(connection_id)`, which
removes the inner dict for that connection from the outer dict. Every
topic the connection had registered and every handler in those topics
is gone in one operation.

This cleanup runs unconditionally on disconnect. It does not depend on
whether the connection held any Elements, whether any of those
Elements had handlers, or whether any of those handlers had been bound
through `publish`. The subscription registry is the only place
connection-scoped state lives; dropping it is the only cleanup the
disconnect path needs.

### Disconnect needs no handler cleanup

When a connection disconnects, the Hub does not walk Elements to find
handlers and uninstall them. The two registries' independence makes
this safe by construction.

Consider the case the handler walk would have addressed: a connection
disconnects, but its scene survives (different ownership, persisted
across the disconnect). The Elements in that scene have handlers
registered against them. Those handlers may include `publish` calls
into topics the disconnecting connection had subscribed to.

The disconnect path drops the connection's subscription scope. The
Elements stay. Their handlers stay registered. If one of those
handlers fires later — because some other connection's click reaches
the surviving Element — the handler runs and may call `Hub.publish` on
the disconnected connection's topic. The publish takes a snapshot of
the topic's subscribers in the disconnected connection's scope; the
scope is gone, the snapshot is empty, the call returns zero. No
observable effect, no error, no leak.

This is the safe no-op property. Orphan handlers that outlive the
connection whose subscriptions they would have driven simply do
nothing useful. They do not crash, they do not leak, they do not block
further publishes. The independence of the two registries is what
makes this trivial — the publish path does not need to know whether
the topic's owning connection still exists; it only needs to know what
subscribers are in the snapshot, and an empty snapshot is the right
answer.

### DisplayClient.recv is deleted in PR 4

The legacy `DisplayClient.recv()` method is removed in PR 4. Every
caller migrates to the new per-connection business-event poller in the
same PR. No shim wraps the new poller for old callers; no
backwards-compatible wrapper carries the old name. After PR 4 the
codebase has one polling interface, with one set of semantics.

The old method returned any wire `Message` from the client's combined
listener queue. The new method returns only payloads from `Hub.publish`
calls scoped to the calling connection — typed business events, not
raw wire frames.

```python
class DisplayClient:

    def poll_event(self, timeout: float) -> Mapping[str, object]:
        """Block for the next business event delivered to this connection.

        Returns the payload of the next ``ObserverMessage`` whose topic
        the connection is subscribed to. Raises ``TimeoutError`` if no
        message arrives within ``timeout`` seconds.
        """
```

The signature reflects the new model. The return type is the payload
itself — a typed `Mapping[str, object]` — not an `ObserverMessage` or
a `Message | None`. Absence is signalled by `TimeoutError`, not by a
sentinel return value; the caller's contract is to either receive a
payload or raise.

Three categories of legacy caller migrate in the same PR:

- Tests that called `recv()` to verify a click roundtripped through the
  client receive a payload from `poll_event` whose shape matches the
  topic they subscribed to. The migration is one line at the call site
  and one assertion-shape change.
- Tests that called `recv()` to drain the listener queue (rather than
  to assert on payload contents) are deleted — the new model has no
  combined queue to drain.
- Agents and applets that polled `recv()` for any-wire-message
  behavior migrate to either `poll_event` (for business events) or to
  the new push path on the bidirectional applet connection (for the
  default async case described in the process topology section).

The deletion is total. The class no longer exposes a method named
`recv`. The wire listener no longer maintains a combined queue. The
client's polling interface is `poll_event` and only `poll_event`.

## Process entry point and HubDisplay

The Hub described in the previous sections — its state, its dispatcher,
its subscription registry — runs inside a single process. That process
needs a binary entry point: the script `pyproject.toml` lists under
`[project.scripts]`, the `main()` function that boots the asyncio loop
and serves connections, the bootstrapper that knows nothing about
domain logic. That entry point belongs in its own module, named for
what it is.

### The luxd module is the process bootstrapper

The process entry point lives at `src/punt_lux/luxd.py`. The module's
job is to start the daemon — parse CLI arguments, bind the display
transport, open the applet TCP listener, install the in-process MCP
tool surface, run the asyncio loop until shutdown. It contains no
domain logic; the domain lives in `domain/hub/`.

```toml
# pyproject.toml — [project.scripts]
luxd = "punt_lux.luxd:main"
```

The name `luxd` is intentional. The conceptual Hub — the object that
owns scene state, dispatches interactions, and runs the subscription
registry — is `domain/hub/`. The process that hosts the Hub is `luxd`.
Naming the entry-point module `hub.py` conflated the two; the
conceptual Hub is not a process, and the process is not the conceptual
Hub.

```python
# src/punt_lux/luxd.py
"""luxd — the Lux daemon. Process entry point.

Boots the asyncio loop, binds the display transport, opens the applet
TCP listener, installs the in-process MCP tool surface, runs until
shutdown. Domain logic lives in ``punt_lux.domain.hub``.
"""

from __future__ import annotations

import argparse
import asyncio

from punt_lux.domain.hub import Hub
from punt_lux.applet import serve_applets
from punt_lux.tools import install_mcp_tools


def main() -> None:
    """Parse arguments, boot the daemon, run until shutdown."""
    args = _parse_args()
    hub = Hub.new(...)
    install_mcp_tools(hub)
    asyncio.run(_serve(hub, args))


async def _serve(hub: Hub, args: argparse.Namespace) -> None:
    """Run the display transport, applet listener, and MCP loop concurrently."""
    ...
```

The module is small. The asyncio plumbing, the argument parser, the
process-lifecycle hooks all live here; nothing else does.

### HubDisplay lands complete

`HubDisplay` is the Hub-side index of every Element by
`(scene_id, element_id)`, plus the owner-tracking metadata that makes
disconnect cleanup correct. It ships complete — every method the
dispatcher, the applier, and the disconnect path need is defined in
the same PR that introduces the dispatcher and the applier.

A minimal placeholder would force callers to test against a partial
surface in this PR and a different surface in the next. That is the
kind of churn the guiding principle exists to prevent. The full class
ships once.

```python
class HubDisplay:
    """Hub-side authoritative index of Elements by (scene_id, element_id)."""

    _by_scene: dict[SceneId, dict[ElementId, Element]]
    _owners: dict[tuple[SceneId, ElementId], ConnectionId]
    _scene_owners: dict[SceneId, ConnectionId]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._by_scene = {}
        self._owners = {}
        self._scene_owners = {}
        return self

    def apply(
        self,
        connection_id: ConnectionId,
        update: AddElement | SetProperty | RemoveElement,
    ) -> None:
        """Commit a state change to the index. Owner is the caller."""
        match update:
            case AddElement(scene_id=sid, parent_id=None, element=elem):
                self._install_scene(sid, elem, owner=connection_id)
            case AddElement(scene_id=sid, parent_id=pid, element=elem):
                self._install_child(sid, pid, elem, owner=connection_id)
            case SetProperty(scene_id=sid, element_id=eid, field=field, value=value):
                self._set_property(sid, eid, field, value)
            case RemoveElement(scene_id=sid, element_id=eid):
                self._remove_subtree(sid, eid)

    def resolve(
        self,
        scene_id: SceneId,
        element_id: ElementId,
    ) -> Element:
        """Return the Element. Raise UnknownElementError if absent."""
        scene = self._by_scene.get(scene_id)
        if scene is None:
            raise UnknownSceneError(scene_id=scene_id)
        element = scene.get(element_id)
        if element is None:
            raise UnknownElementError(
                scene_id=scene_id, element_id=element_id,
            )
        return element

    def owner_of(
        self,
        scene_id: SceneId,
        element_id: ElementId,
    ) -> ConnectionId:
        """Return the connection that installed the Element."""
        return self._owners[(scene_id, element_id)]

    def elements_owned_by(
        self,
        connection_id: ConnectionId,
    ) -> tuple[tuple[SceneId, ElementId], ...]:
        """Return every (scene, element) pair this connection installed."""
        return tuple(
            key for key, owner in self._owners.items()
            if owner == connection_id
        )

    def drop_connection(self, connection_id: ConnectionId) -> None:
        """Mark the connection's owned roots removed; the Element
        Observer cascade prunes the rest."""
        for root in self._owned_roots(connection_id):
            root._mark_removed()
```

`drop_connection` does one thing: call `Element._mark_removed` on
every root Element the connection owns. A "root" is an Element whose
parent is the scene root rather than another Element — i.e., an
Element installed via `AddElement(parent_id=None)`. `_mark_removed`
is the single Element-ABC method that flips `_removed = True` and
fires the observer cascade; the disconnect path uses the same
mechanism as every other removal. Each scene-root container is
observing its children; when a child flips `_removed = True`, the
container's observer fires and performs the same two-step prune any
other removal does — drop the child from its own children tuple AND
call `HubDisplay.apply(RemoveElement(...))` to clear the index entry.
That removal mutates the child, the child's children observe in turn,
and the cascade walks the tree from leaves back up.

`drop_connection` does NOT walk the subtree itself. A direct
`_remove_subtree` loop would bypass the Observer cascade entirely —
parents would never see their children disappear, leaving their own
children tuples stale even as the Hub index drained. The cascade is
the propagation mechanism; `drop_connection` is its trigger.

Three responsibilities, all owned by this one class:

- **Index** — the nested `_by_scene` dict resolves `(scene_id,
  element_id)` lookups in `O(1)`. Every Element the Hub knows about
  lives in this index; no other module holds an authoritative
  reference.
- **Owner tracking** — every Element has a `ConnectionId` that
  installed it. The dispatcher uses this for ownership checks; the
  disconnect path uses it to find every connection-owned root so it
  can mark each one `_removed` and let the Element Observer cascade
  unwind the rest of the tree.
- **Cleanup trigger** — `drop_connection` is the disconnect hook. It
  marks the owned roots `_removed`; the Observer cascade prunes
  children, parents, and the index entries.

The `apply` method dispatches on the typed `Update` sum: a
whole-scene `AddElement` installs a new tree; a child `AddElement`
appends under an existing parent; `SetProperty` mutates a single
field; `RemoveElement` walks the subtree. The pattern-match shape
keeps the dispatch local and the cases exhaustive.

The class is the only place that mutates the index. The dispatcher
calls `resolve` (read-only) before handing the Element to `fire`; the
in-process MCP tools call `apply` to commit updates; the disconnect
path calls `drop_connection`. No third caller reaches into
`_by_scene` directly. The fields stay private; the operations stay
typed.

### Why the conceptual Hub and the process entry point are separate

The Hub is the asyncio-resident object that owns state and dispatches
events. It can be tested without binding a socket, without starting
uvicorn, without parsing arguments — every test in the suite
constructs a `Hub.new(...)` and exercises its methods directly. That
is possible because the Hub is just an object, not a process.

`luxd.py` is the process. Its job is to take a fresh Hub, wire it to
the transports it needs (display, applet, MCP), and run the loop. The
process is hard to test in isolation — it owns sockets, signal
handlers, the asyncio loop itself — and it does not need to be tested
that way. The Hub is the testable surface.

Splitting these two responsibilities into two modules keeps each one
small. Future transports (HTTP, gRPC, anything) add another adapter
in their own package and wire it in `luxd.py`'s startup; they do not
modify the Hub. Future Hub features (a new Update kind, a new event
class, a richer subscription rule) modify the Hub; they do not
modify `luxd.py`. The seam is clean because the two concerns are
genuinely different.

## Applet transport and reference frameworks

Two cross-cutting items remain. The first is the applet transport —
its long-term shape, what this PR documents, and what migrates in the
next PR. The second is the catalog of UI frameworks that informed this
design and that future implementers should consult when a detail
surfaces that none of the design decisions fully specifies.

### Applet transport: line-delimited JSON over TCP

The applet wire protocol is line-delimited JSON over **TCP**. The
choice is deliberate. The system is distributed by design — `luxd`
runs on one host, an applet may run on another, and the protocol must
work across machines. AF\_UNIX is acceptable as a local-loopback
optimization where both ends are on the same host, but it is not the
architectural intent; the wire shape and connection model do not
branch on transport.

Applets hold their TCP connection open bidirectionally for the
connection's lifetime. The same socket carries:

- inbound `subscribe` / `unsubscribe` / `publish` calls from the
  applet to the Hub,
- inbound `apply` calls that mutate scene state,
- outbound `ObserverMessage` deliveries from the Hub to the applet,
- outbound state-mirror updates if the applet observes a scene.

No request / response close-between-calls, no reconnect-per-message,
no separate channel for asynchronous notifications. One socket, one
connection lifetime, both directions. An applet that prefers
synchronous polling may call `poll_event` over the same socket — the
default async path is push, polling is a convenience adapter for
callers that need it.

This document describes the production transport. The actual
migration of the existing in-tree `LineSocket` from AF\_UNIX to TCP
happens with the first applet implementation, when the change has a
concrete consumer and a real cross-host scenario to verify against.
No transport code changes in PR 4; the design doc just stops
mis-describing the long-term shape.

The reason for the explicit deferral is alignment with the guiding
principle. Migrating `LineSocket` without an applet consumer would
leave a transport with no callers — dead code waiting for the next PR
to use it. The transport migrates in the same PR that introduces its
first user, so the change is rollback-coherent: revert the applet,
revert the transport.

### Reference frameworks

Implementation details that the design decisions do not fully specify
are resolved by consulting an ordered list of UI frameworks. Each was
chosen because its shape matches a specific concern of this design;
none was chosen as a wholesale model.

**Primary — JavaFX FXML + Controller.** The closest single match for
this design's wire-format-plus-handler-binding shape. FXML resolves
`onAction="#methodName"` against a typed Controller method at load
time, fails loudly if the method does not exist, and binds the
typed reference into the constructed widget tree. The catalog-plus-
verb-vocabulary pattern this design uses for `call_model` and the
`_ACTIONS` mapping is the same shape: the wire names a verb, the
decoder resolves it against the typed verb mapping at decode time,
the bound reference flows into the constructed Element tree.

**Secondary — SwiftUI.** Typed component composition and
`@Environment`-provided action vocabularies for descendants. The
per-parent-component verb vocabulary pattern (where a Button inside a
Dialog inherits Dialog's verbs and a Button inside a Form inherits
Form's verbs) is SwiftUI's environment pattern. When a future
composite Element needs to provide its own descendant vocabulary, the
SwiftUI environment is the model.

**Tertiary — Vue (template + methods).** Verb-string shorthand
resolving to typed methods. Vue's `@click="methodName"` shorthand
canonicalises to a typed call against the component's methods at
compile time; the parallel here is the sugar wire form (`"publish":
["topic"]`) canonicalising to the long form (`"factory": "noop",
"wrap": [...]`) before the handler chain is built.

**Quaternary — Qt QML signal / slot.** Element Observer mechanics.
Qt's signal/slot system IS the Observer pattern — typed properties
emit typed change signals that subscribers consume by typed slot
methods. When the Element Observer surface grows beyond the
`add_observer(property_name, callback)` shape, Qt's typed signals
are the next reference.

**Quinary — Phoenix LiveView.** Agent-in-a-different-process pattern.
Phoenix `phx-click="event_name"` declares an event name on the client
that the server-side `handle_event/3` callback handles. The
client-server split, the named-event-over-wire shape, and the typed
server-side dispatch all parallel this design's
agent-declares-handler / Hub-dispatches-typed-handler split.

**Not a reference — ImGui.** ImGui is the rendering target for the
display tier, not a model for the io-model. ImGui is immediate-mode:
the renderer redraws the entire UI every frame, the application code
runs every frame, and widgets do not retain state between frames.
This design is retained-mode and declarative: agents describe the UI
once, the Hub holds the Element tree until updated, handlers run on
typed events. The two paradigms are fundamentally different — citing
ImGui as a reference for the io-model would invite a category error.
ImGui's role is exclusively in the rendering tier, drawing the scene
the Hub has assembled.

The ordering matters. When two references suggest different
resolutions for the same detail, the higher-priority one wins. When
no listed reference covers a detail, the implementation is free to
choose — but the chosen shape must be documented in the same commit
as the choice, so a future reader can tell whether the decision was
informed by a reference or was a local invention.

## Commit sequence and acceptance

This PR splits into a sequence of rollback-coherent commits. Each
commit ships a single concern that can be reverted on its own without
leaving the codebase in an incoherent state. The order is driven by
dependency: foundation first, then the dispatch machinery, then the
composite component pattern, then the new wire kind, then the
cleanup of legacy callers.

Every commit ends with `make check` passing and `make update-oo`
staged. Tests covering the commit's invariant are added in the same
commit as the code they verify.

### The commit sequence

1. **Move Hub state into `domain/hub/`; rename `hub.py` → `luxd.py`.**
   Scope: relocate session indexes, locks, the asyncio loop reference,
   and the connection registry from `tools/connection.py` into a new
   `domain/hub/` package. Rename the existing `src/punt_lux/hub.py`
   process-bootstrap module to `src/punt_lux/luxd.py` and update
   `[project.scripts]`. Update every import of the moved symbols in
   the same commit — no shim re-exports.
   *Rollback coherence:* the move and rename are mechanical; rolling
   back leaves the file layout that existed before the PR.

2. **Element ABC with event-driven dispatch.** Scope: introduce the
   `Event` marker Protocol, the `_handlers` registry on the ABC,
   `add_handler` / `remove_handler` / `fire` methods, and the typed
   `Handler[E]` callable shape. No Element kinds use it yet — that
   comes in commits 4 and 5.
   *Rollback coherence:* the new ABC plumbing is additive; without
   callers it is dead surface that comes out cleanly.

3. **Handler catalog scaffolding.** Scope: introduce the per-Element
   typed catalog namespace (`ButtonHandlers`, `DialogHandlers`), the
   decorator factories (`publish` and friends), the wire-spec decoder
   that resolves catalog names and decorator chains, and the
   per-parent verb-vocabulary resolution against `_ACTIONS` mappings.
   Tests cover the long-form and sugar-form wire shapes round-trip
   through the decoder.
   *Rollback coherence:* the catalog has no Element consumers yet,
   so reverting leaves no orphaned imports.

4. **Button and Dialog migration to the new ABC and the MVC pattern.**
   Scope: rewrite `ButtonElement` and `DialogElement` to extend the
   new Element ABC, install handler registries through the catalog
   decoder, and embody the MVC component shape (`DialogModel` private
   to `DialogElement`, child Buttons wired through the bound-callback
   pattern). The existing element implementations are replaced
   wholesale — no parallel old / new classes.
   *Rollback coherence:* the Element kinds are the same names from
   the agent's perspective; reverting reinstates the prior internals
   without changing the wire surface.

5. **Single `ButtonClicked` event; `Display.interact` validation.**
   Scope: introduce the typed `ButtonClicked` dataclass with its
   factory-token guard, the `Display.interact` validation site, and
   the shrunken pump that drops wire-shape triage straight into
   `interact`. Delete `domain/interaction.py`'s `Interaction` sum
   type and `ButtonPressed` in the same commit. Every legacy caller
   migrates to construct `ButtonClicked` through `Display.interact`
   or to receive it as a typed event argument.
   *Rollback coherence:* the new validation site and the deleted
   sum type move together — reverting restores both at once.

6. **Agent Subscribe / Publish with `SubscriptionRegistry` and
   `ObserverMessage`.** Scope: introduce the per-connection-scoped
   `SubscriptionRegistry`, the Hub's `subscribe` / `unsubscribe` /
   `publish` methods with snapshot-then-iterate fan-out, and the
   typed outbound `ObserverMessage` wire kind. Register the new
   message kind in `MessageRegistry`. Add MCP tool surface for
   `subscribe` and `publish`.
   *Rollback coherence:* the registry, the Hub methods, the wire
   kind, and the MCP tools form one functional unit; partial revert
   would leave callers without a target.

7. **Delete `DisplayClient.recv()`; migrate every caller to
   `poll_event`.** Scope: remove the legacy `recv()` method, the
   combined listener queue it drained, and every test or agent that
   called it. Replace each call site with `poll_event` (for business
   events) or with the push path on the bidirectional applet
   connection. No shim, no alias.
   *Rollback coherence:* the deletion and the call-site migrations
   land together — reverting restores both.

8. **Lifecycle wiring and full `HubDisplay`.** Scope: ship the full
   `HubDisplay` class with index, owner-tracking, `apply`,
   `resolve`, `drop_connection`. Wire `drop_connection` into the
   connection-close path so a disconnecting connection's Elements
   are marked `_removed`, the Element Observer cascade prunes the
   surviving tree, and `SubscriptionRegistry.drop_connection`
   purges the connection's topic scope. Confirm via tests that an
   orphan handler firing after its connection is gone is a safe
   no-op.
   *Rollback coherence:* the disconnect path and the lifecycle
   invariants form one concern; reverting brings the partial
   lifecycle that existed before back as a unit.

9. **Interaction trace parity gate.** Scope: a single end-to-end
   test that constructs an in-memory Hub, installs a Dialog with
   Confirm / Cancel children, fires a wire `InteractionMessage` for
   the Confirm click, and asserts every observable downstream
   effect: the typed `ButtonClicked` event reaches the handler, the
   `call_model("confirm")` invocation runs against `DialogModel`,
   `_confirmed = True` is set on the model, the model's `_dismiss`
   callback flips Element-level `_removed = True` through
   `Element._mark_removed`, the Observer cascade reaches the parent,
   the parent prunes the Dialog, and the
   `Hub.publish("dialog_confirmed", ...)` call queues an
   `ObserverMessage` to the subscribing connection. The test is the
   acceptance gate for the PR's behavioral contract.
   *Rollback coherence:* the test depends on every prior commit;
   reverting it removes only the gate, not the behavior.

### Acceptance verification map

Each commit's invariant is verified by a specific test or behavior
check. The map below names each one. `make check` runs all of these
as part of the standard gate; the explicit listing is for review
purposes — so a reader can trace each invariant to its verification.

| # | Invariant | Verification |
|---|-----------|--------------|
| 1 | Hub state lives in `domain/hub/`; entry point is `luxd.py` | `tests/test_module_layout.py` asserts the package layout; `pyproject.toml`'s `[project.scripts]` parses and the `luxd` script imports cleanly |
| 2 | Element ABC dispatches typed events to registered handlers | `tests/test_element_abc.py::test_fire_invokes_registered_handler` registers a handler and asserts the event reaches it; a second test asserts a handler that mutates the registry mid-dispatch does not break the in-flight call |
| 3 | Wire spec → handler chain via catalog and decorators | `tests/test_handler_catalog.py` round-trips both the long form and the sugar form through the decoder; asserts the constructed `Handler[E]` chain calls the inner factory followed by each decorator in order |
| 4 | Dialog dismisses itself when Confirm is clicked | `tests/test_dialog_element.py::test_confirm_marks_removed` constructs the Dialog through the decoder, fires a click on the Confirm child, asserts `_confirmed` on the model and `_removed` on the owning DialogElement, and that the Element-level Observer notified the parent |
| 5 | `ButtonClicked` is constructed only by `Display.interact`; validation lives in one site | `tests/test_button_clicked.py::test_direct_construction_raises` calls `ButtonClicked(...)` directly and asserts `TypeError`; `tests/test_display_interact.py` parametrizes the four validation failures (unknown client, unknown scene, unknown element, wrong kind) and asserts the typed error each raises |
| 6 | Per-connection scoping; `ObserverMessage` round-trips on the wire | `tests/test_subscription_registry.py::test_per_connection_scope` subscribes two connections to the same topic name and asserts a publish from one reaches only its own subscribers; `tests/test_observer_message.py` round-trips the wire shape through the `MessageRegistry` |
| 7 | `poll_event` is the only polling interface; `recv` is gone | `tests/test_display_client.py::test_no_recv_attribute` asserts `hasattr` returns False; `tests/test_display_client.py::test_poll_event_returns_payload` subscribes, publishes from another connection-handle, asserts the payload arrives |
| 8 | Disconnect cascades through the Element Observer and drops the topic scope | `tests/test_lifecycle.py::test_disconnect_prunes_owned_elements` installs Elements under a connection, disconnects, asserts the Elements are gone from `HubDisplay`'s index and the parent's `children` tuple shrank; `tests/test_lifecycle.py::test_orphan_handler_publish_is_safe_noop` keeps a registered handler alive after its connection drops and asserts a publish call returns zero subscribers without raising |
| 9 | End-to-end Dialog interaction trace | `tests/test_interaction_trace.py::test_confirm_click_to_observer_message` runs the full path: wire `InteractionMessage` → `Display.interact` → `ButtonClicked` → `Element.fire` → catalog handler → `DialogModel.confirm` → Observer cascade → parent prune → `Hub.publish` → `ObserverMessage` queued for the subscribing connection |

`make check` is the gate at every commit; the test files above are
additive at each step. A commit that ships its scope without
verification — or with verification that does not assert the
invariant the commit's text claims — is not ready to land.
