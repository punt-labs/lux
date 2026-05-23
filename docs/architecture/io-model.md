# I/O Model — Decoder, Element, Renderer

**Author:** Claude Agento (claude)
**Date:** 2026-05-23
**Status:** TARGET (not yet implemented).
**Companion docs:** [`domain-model.md`](domain-model.md) (the domain north star),
[`x11-model.md`](x11-model.md) (the process topology),
[`migration-plan.md`](../oo-refactor/migration-plan.md) (how we get there).

This document is the target architecture for how data flows IN to the Lux
domain (decoders) and how the domain manifests OUT to a surface (renderers).
PR 1 and PR 2 of the OO migration shipped the domain layer; this doc
describes the layer that surrounds it.

## Principles

These are non-negotiable. The rest of the document is consequences of
applying them.

1. **The Element is a domain object.** State, behavior, composition. Not a
   transport struct, not a render widget. It owns what happens to it —
   on click, on drag, on minimize, on maximize, on value change.

2. **The Element does not know its inputs or outputs.** No imports of any
   wire format, no imports of any render surface. The Element knows the
   abstract `RendererFactory` Protocol so it can render itself; that is
   the only I/O knowledge it carries.

3. **The Composite pattern lives on the Element itself.** Same `render()`
   method on leaf and composite, inherited from a shared base via the
   template method pattern. Composites recurse on children through the
   same Protocol. No external dispatcher.

4. **I/O is symmetric.** Decoding wire-format input and rendering to a
   surface are structurally identical concerns — both are external,
   both have multiple possible implementations, both are selected via a
   key→family registry. The implementation responsibilities differ;
   the architectural shape does not.

5. **Input fans in; output is singular.** One Display has one render
   surface but many connected clients, each potentially using a
   different wire format. This is the only deliberate asymmetry.

## The Element — domain core

Every Element class inherits from an abstract base that owns the render
lifecycle. Subclasses declare state and behavior, never `render()`.

```python
class Element(ABC):
    """Domain component. Owns its render lifecycle via the template method
    pattern. Composite participants (leaf and composite) share the same
    render() — recursion is internal to the template."""

    _renderer_factory: RendererFactory
    _emit:             Emit

    def __new__(cls, *, renderer_factory: RendererFactory, emit: Emit,
                **kwargs: Any) -> Self:
        self = super().__new__(cls)
        self._renderer_factory = renderer_factory
        self._emit             = emit
        # subclass __new__ assigns its own fields before return
        return self

    def render(self) -> None:
        """Template method — never overridden. Leaf vs composite branch
        is the only logic here; behavior lives on subclasses; drawing
        lives on the resolved Renderer."""
        renderer = self._renderer_factory(self)
        children = self._children()
        if children:
            renderer.begin()
            try:
                for child in children:
                    child.render()
            finally:
                renderer.end()
        else:
            renderer.render()

    def _children(self) -> tuple[Element, ...]:
        """Hook — composites override to return their children. Leaves
        inherit the empty default and the template takes the leaf branch."""
        return ()
```

### Leaf — declare fields, declare behavior, nothing else

```python
class ButtonElement(Element):
    _id:       str
    _label:    str
    _action:   str
    _disabled: bool

    def __new__(cls, *, renderer_factory: RendererFactory, emit: Emit,
                id: str, label: str, action: str | None = None,
                disabled: bool = False) -> Self:
        self = super().__new__(cls, renderer_factory=renderer_factory, emit=emit)
        self._id       = id
        self._label    = label
        self._action   = action or id
        self._disabled = disabled
        return self

    # ----- behavior — domain knowledge of what user actions mean -----
    def on_click(self) -> None:
        """A click on this button emits its action to the interaction
        channel. Subclasses with richer button semantics (toggle button,
        radio peer, etc.) override this method to encode the domain rule."""
        self._emit(InteractionMessage(
            element_id=self._id, action=self._action,
            ts=time.time(), value=True,
        ))

    # No render() — inherited.
    # No _children() — inherited (empty tuple, leaf branch in template).

    # Read-only state access for renderers that need to read fields.
    @property
    def id(self)       -> str:  return self._id
    @property
    def label(self)    -> str:  return self._label
    @property
    def disabled(self) -> bool: return self._disabled
```

### Composite — declare children, inherit render template

```python
class GroupElement(Element):
    _id:                 str
    _children_tuple:     tuple[Element, ...]

    def __new__(cls, *, renderer_factory: RendererFactory, emit: Emit,
                id: str, children: tuple[Element, ...]) -> Self:
        self = super().__new__(cls, renderer_factory=renderer_factory, emit=emit)
        self._id = id
        self._children_tuple = children
        return self

    def _children(self) -> tuple[Element, ...]:
        return self._children_tuple

    # No render() — inherited template handles composite branch via _children().
```

### What Element does NOT do

- It does not import `imgui`, `html`, or any surface library.
- It does not import any wire format module (`json`, `msgpack`, etc.).
- It does not define `to_dict` / `from_dict` / `to_msgpack` / etc.
  Codec is a Decoder/Encoder concern (see below). The PR 1+2 decision
  to put codec methods on the class was an over-application of PY-OO-5
  — codec is an I/O concern, not domain behavior.
- It does not emit InteractionMessages directly from a renderer's click
  detection. The renderer calls `elem.on_click()`; the Element decides
  what (if anything) to emit. The behavior is the Element's, not the
  renderer's.

## The Renderer family — output side

### Surface — a key, not an object

```python
class Surface(Enum):
    IMGUI     = "imgui"
    HTML      = "html"
    RECORDING = "recording"
    NULL      = "null"
```

`Surface` has no methods. It is a constrained discriminator the Renderers
registry uses to pick a family.

### Renderer Protocol — the Composite Component on the render side

```python
class Renderer(Protocol):
    """The contract every per-kind renderer satisfies. Leaves implement
    render(); composites implement begin() and end() — the Element
    template method calls the appropriate set based on _children()."""

    def render(self) -> None:                # leaves draw the thing
        ...

    def begin(self) -> None:                 # composites: open the bracket
        ...

    def end(self) -> None:                   # composites: close the bracket
        ...
```

In practice each per-kind renderer class implements the relevant subset.
Two narrower Protocols (`LeafRenderer`, `CompositeRenderer`) can replace
this union for type clarity; the Element template treats them uniformly.

### RendererFactory — callable

```python
class RendererFactory(Protocol):
    """Callable that resolves an Element to its per-kind Renderer for
    this surface. One factory per Surface per Display."""
    def __call__(self, elem: Element) -> Renderer: ...
```

A concrete factory holds the surface-shared context (ImGui IO handle,
HTML output buffer, recording list) and dispatches by Element type:

```python
class ImGuiRendererFactory:
    _widget_state: WidgetState
    # ... other ImGui-side shared context ...

    def __call__(self, elem: Element) -> Renderer:
        match elem:
            case ButtonElement():
                return ImGuiButtonRenderer(elem)
            case GroupElement():
                return ImGuiGroupRenderer(elem)
            case ...:
                ...
```

### Per-kind renderers

Each surface family has one renderer class per Element kind. Renderers
hold a reference to the Element (read-only) and any surface-shared state.

The example below shows the **owner-tier** path — i.e. the renderer
running in the process that constructed the Element subclass and bound
its `on_click` behavior (typically an in-process applet, or the hub for
hub-local handlers). In this case the renderer can call
`self._elem.on_click()` directly because the bound behavior lives in
the same process.

On a **non-owner tier** (the display process for an applet-owned button,
which holds only a base-class mirror of the Element), the renderer
does NOT call `on_click()`; it emits an `InteractionMessage` that the
hub routes back to the owner. See *Tier-local Element representation*
below (around line 620) and the end-to-end click trace that follows it
for the full cross-tier flow.

```python
class ImGuiButtonRenderer:
    _elem: ButtonElement
    def render(self) -> None:
        if self._elem.disabled: imgui.begin_disabled()
        try:
            if imgui.button(f"{self._elem.label}##{self._elem.id}"):
                self._elem.on_click()    # OWNER-TIER ONLY — see note above
        finally:
            if self._elem.disabled: imgui.end_disabled()

class HtmlButtonRenderer:
    _elem: ButtonElement
    _out:  list[str]
    def render(self) -> None:
        attrs = f' id="{html.escape(self._elem.id)}"'
        if self._elem.disabled: attrs += " disabled"
        self._out.append(
            f"<button{attrs} onclick=\"luxClick('{self._elem.id}')\">"
            f"{html.escape(self._elem.label)}</button>"
        )
        # JS handler luxClick() eventually reaches the owner tier (where
        # on_click is bound) via the websocket round-trip back to the
        # server — same cross-tier routing as the ImGui non-owner case.

class ImGuiGroupRenderer:
    _elem: GroupElement
    def begin(self) -> None: imgui.begin_group()
    def end(self) -> None:   imgui.end_group()
```

### Renderers registry

```python
class Renderers:
    @staticmethod
    def getRendererFor(surface: Surface, **context: Any) -> RendererFactory:
        match surface:
            case Surface.IMGUI:     return ImGuiRendererFactory(**context)
            case Surface.HTML:      return HtmlRendererFactory(**context)
            case Surface.RECORDING: return RecordingRendererFactory(**context)
            case Surface.NULL:      return NullRendererFactory()
            case _: assert_never(surface)
```

Renderers is module-level. One render factory exists per Display, chosen
at startup.

## The Decoder family — input side

Structurally identical to the Renderer family.

### WireFormat — a key, not an object

```python
class WireFormat(Enum):
    JSON     = "json"
    MSGPACK  = "msgpack"
    CBOR     = "cbor"
    PROTOBUF = "protobuf"
```

### Decoder Protocol

```python
class Decoder(Protocol):
    """Reads wire bytes for one format, produces fully-constructed Elements
    with renderer_factory and emit injected at construction."""
    def decode(self, raw: bytes) -> Element: ...
```

### Per-format per-kind decoders

```python
class JsonButtonDecoder:
    _renderer_factory: RendererFactory
    _emit:             Emit

    def decode(self, raw: dict) -> ButtonElement:
        return ButtonElement(
            renderer_factory=self._renderer_factory,
            emit=self._emit,
            id=raw["id"],
            label=raw["label"],
            action=raw.get("action"),
            disabled=raw.get("disabled", False),
        )

class MsgpackButtonDecoder:
    # same shape, different bytes-to-dict step (msgpack.unpackb)
    ...
```

### DecoderFactory and Decoders registry

```python
class DecoderFactory(Protocol):
    """Top-level decoder for a wire format. Owns per-kind decoders.
    Constructed once per connection (or per format negotiation result)."""
    def decode(self, raw: bytes) -> Element: ...

class Decoders:
    @staticmethod
    def getDecoderFor(fmt: WireFormat, renderer_factory: RendererFactory,
                      emit: Emit) -> DecoderFactory:
        match fmt:
            case WireFormat.JSON:     return JsonDecoderFactory(renderer_factory, emit)
            case WireFormat.MSGPACK:  return MsgpackDecoderFactory(renderer_factory, emit)
            case WireFormat.CBOR:     return CborDecoderFactory(renderer_factory, emit)
            case WireFormat.PROTOBUF: return ProtobufDecoderFactory(renderer_factory, emit)
            case _: assert_never(fmt)
```

A `JsonDecoderFactory` owns per-kind decoders (JsonButtonDecoder,
JsonGroupDecoder, …) and dispatches by `raw["kind"]` to the right one.

## Cardinality and lifecycle

| | Selected when | Lifetime | Count per Display |
|---|---|---|---|
| `RendererFactory` | Display startup | process | 1 |
| `Decoder` | client connect (format negotiation or scheme) | connection | N |

The output surface is singular — a Display has one renderer. The input
fans in: each connected client/app can speak its own wire format.

```text
              CLIENTS / APPS  (N — different formats, different identities)
        ┌────────────┬────────────┬────────────┐
Python  │   JSON     │            │            │
Go      │            │  MSGPACK   │            │
Rust    │            │            │   CBOR     │
        └─────┬──────┴──────┬─────┴──────┬─────┘
              │             │            │
              ▼             ▼            ▼
        ┌──────────┬──────────────┬──────────┐
        │   Json   │   Msgpack    │   Cbor   │  DECODERS (N — one per connection,
        │  Decoder │   Decoder    │  Decoder │  configured with the same
        │  Factory │   Factory    │  Factory │  renderer_factory + emit)
        └─────┬────┴───────┬──────┴──────┬───┘
              │            │             │
              ▼            ▼             ▼
        ┌─────────────────────────────────────┐
        │       Display + Element trees       │  ONE Display
        │   (state + behavior + composition)  │  (multi-tenant scenes,
        │                                     │   ownership by client_id)
        └────────────────────┬────────────────┘
                             │
                             ▼  Element.render() — template, no branching
                  ┌─────────────────────────┐
                  │     RendererFactory     │  ONE — chosen at startup
                  │     (e.g. ImGui)        │
                  └────────────┬────────────┘
                               │
                               ▼
                       ┌───────────────┐
                       │ Output surface│  ImGui window, HTML page,
                       │   (the one    │  recording buffer — one
                       │   display)    │  per Display
                       └───────────────┘
```

## Construction paths and deployment topologies

The Element class is constructed through Python's ordinary constructor. The
Decoder family is one source of constructor arguments — bytes-in, Element-out
— but not the only one. Native Python applets that import the `punt_lux`
library construct Elements directly, with no wire format involved on the
applet side.

### Construction paths — language is the axis, not process

Every applet defaults to its own process. The applet → hub IPC boundary is
the same in every case; the wire format is the same (JSON today, others
when registered). What differs is **how the applet author constructs the
thing that goes on the wire**:

| Path | Applet language | What the author writes | Wire format on the IPC boundary | Typical use |
|------|----------------|------------------------|---------------------------------|-------------|
| **Foreign-language applet** | Go, Rust, TypeScript, … | JSON dicts assembled manually (or via a language-native helper library that does the assembly). | JSON. Author sees it. | Polyglot Lux apps. |
| **Python applet (default)** | Python | Native `ButtonElement(...)` / `GroupElement(...)` constructor calls using the `punt_lux` library. Local Display proxy serializes Updates invisibly at the IPC boundary. | JSON. Author does not see it. | Python Lux apps. |
| **In-process (rare)** | Python | Same Python constructor calls, but applet + hub + display are all in the same process. No IPC, no serialization. | NONE. | Domain unit tests; single-process embedded use cases. |

The Python-applet path and the foreign-language-applet path produce
**identical bytes on the IPC boundary**. The hub's `JsonDecoderFactory`
doesn't and can't tell the difference between "this JSON came from
Python's library auto-serializer" and "this JSON came from a Go applet
that wrote it by hand." The point of the library is to spare Python
authors from writing the JSON, not to use a different protocol.

The Decoder family is the path for **crossing IPC boundaries between
processes**. It is invoked even when the applet is Python — just
invisibly, by the applet's library code. The only path where no Decoder
is invoked at all is the in-process path, and that one is reserved for
tests and embedded scenarios.

### Deployment topology — the default

Three processes, one tier each:

```text
┌──────────────────┐       ┌─────────────────┐       ┌────────────────┐
│  Applet process  │◄─────►│   Hub (luxd)    │◄─────►│  lux-display   │
│  (punt_lux lib)  │ IPC + │  authoritative  │ IPC + │  render-only   │
│  Element ctors   │ JSON  │   Display       │ JSON  │   Display      │
└──────────────────┘       └─────────────────┘       └────────────────┘
        ▲                                                     │
        │                                                     ▼
   Applet author                                       ImGui window
   writes Python                                       (the surface)
```

Every tier holds the same `Display` class, the same Element types, the same
Renderer / Decoder / Encoder families. The differences:

- **Applet process** runs Python that *constructs* Elements via the library
  and *subscribes* to Events emitted back to it. Its local Display is a
  proxy that serializes Updates outbound and decodes Events inbound.
- **Hub process** holds the authoritative Display. Receives Updates from
  every applet (decoded via per-connection JsonDecoder); emits Events to
  applets (encoded via per-connection JsonEncoder); forwards canonical
  Updates to the display (via the hub→display Decoder/Encoder pair).
- **Display process** holds a render-only Display. Receives Updates from
  the hub, renders via `ImGuiRendererFactory`; forwards user-driven
  Interactions back to the hub.

The Decoder/Encoder serves *every* cross-process boundary in this topology,
not just hub↔display. The cardinality model from DES-033 generalizes: the
hub has N decoders (one per inbound connection — applets are inbound;
display is inbound for Interactions) and N encoders (one per outbound
connection — applets get Events; display gets Updates).

### Where rendering happens — IPC and rendering are decoupled

**IPC carries Updates and Events. Not render calls.** The Decoder/Encoder
families serialize state changes (Updates) and notifications (Events).
Rendering is a per-tier concern, and a tier renders by iterating its
OWN `Display`'s scene with its OWN `RendererFactory`.

**Only the display tier has a render loop in the default deployment.**
The display process holds an ImGui main loop that iterates its `Display`'s
scene every frame and calls `elem.render()` to draw. The hub and applet
processes have no render loop — they have message loops that propagate
Updates and Events.

The flow when an applet adds an element:

```text
Applet                  Hub                       Display
─────                   ───                       ───────
Construct ButtonElement
elem stored locally
display.apply(client,
   AddElement(elem))
  └─ Update → IPC ────► recv Update
                        decode Update via JsonDecoder
                        hub_display.apply(client, AddElement(...))
                          └─ mutate hub state
                          └─ emit Update → IPC ──► recv Update
                                                    decode via JsonDecoder
                                                    display_display.apply(...)
                                                      └─ mutate display state
                                                      └─ emit ElementAdded
                                                         to subscribers
                                                    (next frame, render loop
                                                     iterates the scene and
                                                     calls elem.render() ──►
                                                     ImGui drawing)
```

No render call crosses any IPC boundary. The display's render loop draws
what's in its scene every frame, independent of any IPC activity. IPC
just changes what's IN the scene. The render loop and IPC run in
parallel, in their own tiers, connected only by the scene state IPC
maintains.

**What this means for `renderer_factory` injection on Element:**

`renderer_factory` is only meaningful in a tier that has a render loop —
in the default deployment, only the display tier. So:

- **Display tier:** the Decoder constructing inbound Elements injects
  `ImGuiRendererFactory`. `elem.render()` actually draws every frame.
- **Hub tier:** the Decoder constructing inbound Elements injects
  `NullRendererFactory`. The hub never iterates its scene for drawing;
  the injected factory is dead weight but keeps the constructor signature
  uniform across tiers.
- **Applet tier:** the applet constructs Elements with
  `NullRendererFactory` by default. The applet has no render loop in
  default deployment. If the applet wants its own local preview window,
  it constructs an `ImGuiRendererFactory` against its own local ImGui
  context and runs its own render loop — an in-process display embedded
  in the applet process, NOT remote rendering.

**Why not a RemoteRenderer?** A RemoteRenderer would mean `elem.render()`
in one tier serializes a "render this element" request over IPC to
another tier. That conflates render-call propagation (which would happen
on-demand) with state propagation (which happens via Updates). It also
mismatches how ImGui works — ImGui polls the scene every frame; you
don't tell it "render this now." The cleaner separation is: state
crosses IPC via Updates; rendering happens locally in whichever tier
has a render loop.

### What this is not

- The applet author does NOT write JSON. They write Python with the
  punt_lux library.
- The applet does NOT need a different Element class hierarchy from the
  hub. Same classes, same ABC, same render template, same behavior methods.
- The applet does NOT need to know it is in a separate process. The
  LocalDisplayProxy (or whatever the applet-side Display abstraction is
  named when it ships) hides the IPC boundary; applet code calls
  `display.apply(client_id, AddElement(...))` exactly as if Display were
  local.
- The applet is NOT REQUIRED to be in a separate process. The architecture
  supports in-process embedding for tests and for special-purpose
  scenarios; separate-process is the default for production applets.

### What this enables

- **Python applet authors write Python, not JSON.** They `import punt_lux`,
  construct `ButtonElement(...)`, attach behavior, subscribe to Events.
  The wire is invisible.
- **The same domain code runs in all tiers.** Applet, hub, and display all
  import the same Element / Display / Renderer modules. The codec is at
  the IPC boundary, not woven through application logic.
- **External-language agents and Python applets coexist** on the same hub.
  Same display, same Display.apply semantics, same scene-graph invariants.
- **Tests construct Elements directly** against an in-process Display. No
  decoder, no IPC, no surface. The Element class is fully constructable
  in pure Python.

## Wiring example — startup, connect, message, render

```python
# ─── Display startup (once) ──────────────────────────────────────────
display          = Display()
renderer_factory = Renderers.getRendererFor(Surface.IMGUI,
                                            widget_state=display.widget_state)
emit             = display.interact_channel   # routes back to client by ownership


# ─── Per client connect (N times, possibly different formats) ─────────
def on_client_connect(conn: Connection) -> None:
    fmt     = conn.negotiate_format()   # detect/negotiate — sniff first bytes,
                                        # or read a scheme tag, or per-port convention
    decoder = Decoders.getDecoderFor(fmt, renderer_factory, emit)
    conn.bind_decoder(decoder)


# ─── Per scene message (many times per connection) ─────────────────────
def on_message(conn: Connection, raw_bytes: bytes) -> None:
    element = conn.decoder.decode(raw_bytes)
    display.apply(conn.client_id,
                  AddElement(scene_id=conn.scene_id, element=element))


# ─── Per frame (~60Hz) ────────────────────────────────────────────────
def render_frame() -> None:
    for scene_id, scene_root in display.scene_roots():
        scene_root.render()    # template; all clients' elements render via
                               # the same renderer_factory regardless of which
                               # format their wire payload arrived in
```

## Tier-local Element representation — NOT three identical instances

A single conceptual button has DIFFERENT representations in each tier
where it appears. They share an Element abstract base and the same data
fields, but they are not interchangeable:

```text
   applet process           hub process               display process
   ──────────────           ───────────               ───────────────

   class SubmitButton       ButtonElement             ButtonElement
   (ButtonElement):         (base class — data        (base class — data
       def on_click(self):   only; no behavior         only; no behavior
           # custom logic    method bindings —         method bindings —
           ...               applet's code is NOT      applet's code is NOT
                             in this process)          in this process)

   Bound behavior?  YES     Bound behavior?  NO       Bound behavior?  NO
   (applet wrote on_click   (decoded from wire        (decoded from wire
    on this subclass)        as the base class)        as the base class)

   _renderer_factory:       _renderer_factory:        _renderer_factory:
     NullRendererFactory      NullRendererFactory       ImGuiRendererFactory
     (applet has no render    (hub has no render        (the render loop
      loop in default          loop)                     here calls
      deployment)                                        elem.render())
```

The applet's process is the only one that has the customized subclass
with the bound `on_click` method. Hub and display decode the wire payload
into the BASE `ButtonElement` (they don't have the applet's Python
source) — they hold data + the abstract render template + their
tier-appropriate factory.

When a click happens, the display tier's renderer does NOT call
`elem.on_click()` on its local Element instance — its local instance has
no custom behavior. Instead, the renderer emits an `InteractionMessage`
identifying the element. That message routes via the hub to the owner
(applet), and the applet's local instance — the one with the custom
on_click — runs the behavior.

### End-to-end trace of a single Button click (corrected)

Setup: a Python applet has constructed `SubmitButton(id="submit", action="do_submit")`
and called `display.apply(applet_client_id, AddElement(scene, submit))`. The
Update has propagated applet → hub → display; the button is on screen.

```text
1. Display's ImGui render loop (60 Hz frame):
   scene_root.render() walks display's Element tree.
   ButtonElement.render()  [Element ABC template]
     renderer = self._renderer_factory(self)   # ImGuiRendererFactory
     renderer.render()                          # ImGuiButtonRenderer
       imgui.button("Submit##submit") → False this frame
       (no click)

2. User clicks. Next frame:
   ImGuiButtonRenderer.render()
     imgui.button("Submit##submit") → True
     Renderer emits InteractionMessage(
         element_id="submit", action="do_submit", value=True, ts=...)
     via the display tier's Encoder for the hub connection.

3. Hub receives the InteractionMessage:
   Decoder decodes JSON → InteractionMessage object.
   Hub looks up owner of element_id="submit" → applet_client_id.
   Hub re-encodes the message via the applet connection's Encoder,
   pushes via IPC to the applet.

4. Applet receives:
   Decoder decodes → InteractionMessage.
   Applet's local Display proxy delivers it to subscribers.
   Applet's runtime finds its local SubmitButton instance by element_id="submit"
   and calls submit.on_click()  — the custom subclass method runs HERE.

5. Inside on_click(), the applet mutates its local scene:
       self.scene.replace_with(SuccessScene())
   This produces Updates the applet's local Display proxy emits.

6. Updates flow applet → hub → display.
   Hub applies them to hub_display.
   Hub re-encodes the whole tree (ImGui downstream) or diffs (HTML downstream)
   and ships to display.

7. Display applies Updates to its mirror.
   Next frame: render loop draws the new state.
```

Substituting `Surface.HTML` changes only the display-side render
(steps 1–2: HTML emission + websocket round-trip for the click). Substituting
`WireFormat.MSGPACK` for the applet↔hub or hub↔display IPC changes only
the bytes on those boundaries (steps 3, 6). Element subclass, behavior
method, scene mutation, render template — none of it shifts.

## Handler routing — three independent axes

When an InteractionMessage arrives at the hub, routing decisions decompose
into three independent axes. Conflating them caused several false
proposals during design discussion; documenting the split is what made
the design coherent.

```text
   AXIS 1 — OWNERSHIP        Who runs the handler? Two cases:
                               • "hub"           → hub runs in-place
                               • <connection_id> → hub forwards to that conn
                             (The hub maintains {element_id → owner}.)

   AXIS 2 — CLIENT KIND      How does the recipient connection dispatch?
                             Only meaningful if owner is a connection.
                               • LIBRARY CLIENT  (Python applet using
                                 punt_lux)   → dispatches to local
                                 Element instance's Python method
                               • WIRE CLIENT  (Go/Rust/external Python
                                 emitting JSON over MCP)  → dispatches
                                 via its own switch on message fields
                               • LLM AGENT  (special case of wire client
                                 where dispatch IS prompt interpretation)
                                 → LLM reads message, decides what to
                                 do, emits Updates back

   AXIS 3 — HANDLER PATTERN  What does the handler body actually do?
                             Independent of who runs it.
                               • DETERMINISTIC  — straight code,
                                 returns synchronously, produces Updates
                                 locally
                               • AGENT-ESCALATION  — builds a prompt,
                                 sends to an LLM, waits for response,
                                 emits Updates after
                               • HYBRID  — does some deterministic
                                 work, then escalates for the part
                                 that requires reasoning
```

The hub only cares about axis 1. The recipient connection's runtime
handles axis 2 internally. Axis 3 is the handler-body author's choice
and is invisible to both the hub and the runtime.

Examples in practice:

```text
   ownership      client kind        handler pattern        example
   ─────────      ───────────        ───────────────        ───────
   hub            (n/a)              deterministic          FilterableTable's
                                                            on_filter_change
   connection     library            deterministic          Beads applet's
                                                            update-bead button
   connection     library            agent-escalation       Python applet that
                                                            calls its own LLM
   connection     LLM agent          agent-escalation       Claude Code
                                                            modal confirm
   connection     wire client (Go)   deterministic          Go applet that
                                                            switches on action
```

## Sequence diagrams — four canonical cases

Each diagram shows a routing rule the others don't. Handler-body
variations (external CLI side effects, network calls, etc.) reduce
to one of these four cases — invisible to the hub and to routing.

### Seq 1 — Hub-local data table filter (owner = "hub", deterministic)

```text
USER          DISPLAY                     HUB
 │             │                           │
 │             │   ◄────── Update tree ────┤   FilterableTable in
 │             │   render, draw table      │   hub_display (built-in
 │             │                           │   hub-shipped class)
 │             │                           │
 type "a" ────►│   ImGui detects keystroke │
 in filter     │   InputText.on_change     │
               │   → InteractionMsg        │
               │     action="filter",      │
               │     value="a"             │
               │   ──────── IPC ──────────►│   lookup owner of input
               │                           │   → "hub"
               │                           │   dispatch IN-PLACE:
               │                           │     table.on_filter_change("a")
               │                           │     mutates visible_rows
               │                           │   re-encode whole tree
               │   ◄──────── IPC ──────────┤   ship to display
               │   apply, render           │
               │   draws filtered rows     │
 USER sees     │                           │
 filtered      │                           │
 table         │                           │
```

### Seq 2 — Modal confirm to Claude Code (owner = CC connection, LLM agent, agent-escalation)

```text
USER         DISPLAY              HUB                    CLAUDE CODE (agent)
 │            │                    │                      │
 │            │                    │  ◄──── MCP ──────────┤  show_modal(
 │            │                    │    decode JSON       │    title="Apply patch?",
 │            │                    │    AddElement(modal) │    buttons=["Yes","No"])
 │            │                    │    owner = CC's conn │
 │            │   ◄── Update tree ─┤    re-encode tree    │
 │            │   render, draw     │                      │
 │            │   modal w/ Yes/No  │                      │
 │            │                    │                      │
 USER sees ──►│                    │                      │
 modal        │                    │                      │
 click "Yes"─►│   ImGui detects    │                      │
              │   Button "Yes"     │                      │
              │   → InteractionMsg │                      │
              │     action="yes"   │                      │
              │   ──── IPC ───────►│   lookup owner of    │
              │                    │   "Yes" button       │
              │                    │   → CC's connection  │
              │                    │   ──── MCP ─────────►│   receives Interaction
              │                    │                      │   LLM interprets:
              │                    │                      │     "user confirmed Yes,
              │                    │                      │      proceed with patch"
              │                    │                      │   runs the deferred action
              │                    │                      │   → tool call: clear modal
              │                    │   ◄──── MCP ─────────┤   clear(scene="modal")
              │                    │   decode             │
              │                    │   RemoveElement      │
              │   ◄── Update tree ─┤   re-encode tree     │
              │   render, draw     │                      │
              │   modal gone       │                      │
```

### Seq 3 — Python applet filter input (owner = applet conn, library client, local deterministic)

```text
USER       DISPLAY              HUB                 APPLET (Python)
 │          │                    │                   │
type "x" ──►│ ImGui InputText    │                   │
            │ InteractionMsg     │                   │
            │ ──── IPC ─────────►│ owner = applet conn
            │                    │ ──── IPC ────────►│ runtime finds local
            │                    │                   │ FilterInput instance
            │                    │                   │ filter.on_change("x")
            │                    │                   │ applet.filter = "x"
            │                    │                   │ applet.recompute_visible()
            │                    │                   │ emits Updates
            │                    │ ◄──── IPC ────────┤
            │ ◄──── IPC ─────────┤ apply, re-encode  │
            │ shows filtered     │                   │
            │ list               │                   │
                              (no external system touched)
```

> **Handler bodies with external side effects (CLIs, DBs, network)** route
> identically to Seq 3. The applet's `on_click` may call `subprocess.run(["bd",
> "update", …])`, hit a database, make an HTTP request, etc. The hub and
> display see nothing different — InteractionMessage in, Updates out. The
> side effects are internal to the handler body and invisible to routing.

### Seq 4 — Python applet "Queue Work" notifies agents via MCP-bridged Observer (async)

```text
USER     DISPLAY        HUB                  APPLET                  AGENT (observer
 │        │              │                    │                       of "bead.queued")
click ───►│              │                    │                       │
          │ Button       │                    │                       │
          │ Interaction  │                    │                       │
          │ ── IPC ─────►│ ── IPC ───────────►│ queue.on_click()      │
          │              │                    │ build work spec       │
          │              │                    │ hub.publish(          │
          │              │                    │   topic="bead.queued",│
          │              │                    │   payload=spec)       │
          │              │ ◄── PublishMessage ┤                       │
          │              │ (Lux IPC wire kind)│ mark UI "queued"      │
          │              │ subscription       │ emits Updates         │
          │              │ registry lookup:   │                       │
          │              │ subscribers of     │                       │
          │              │ "bead.queued"      │                       │
          │              │ → [agent_conn, …]  │                       │
          │              │ for each sub:      │                       │
          │              │ ── MCP notification observed(topic, payload) ────►│ receives
          │              │ ◄── IPC ───────────┤                       │ notification
          │ ◄── IPC ─────┤ apply, re-encode   │                       │ LLM interprets,
          │ row shows    │                    │                       │ decides action
          │ "queued"     │                    │                       │
          │              │                    │                       │ (async — applet's
          │              │                    │                       │  handler already
          │              │                    │                       │  returned; observer
          │              │                    │                       │  count could be 0
          │              │                    │                       │  or N)
          │              │ ◄── MCP tool call (client → server) ───────┤ e.g.
          │              │ decode, AddElement / SetProperty             bd_update or
          │              │ apply to hub_display, re-encode tree         update Lux
          │ ◄── IPC ─────┤                    │                       │ element
          │ shows result │                    │                       │
              (Two UI updates: first "queued" (sync from applet), then
               "done" later (async from agent). Applet did not name the
               agent — it published a topic; the hub fanned out to every
               subscriber. Loose coupling per DES-036.)
```

## Agent observers — MCP boundary

Inside the Lux fabric (applet ↔ hub ↔ display), state-change messages
are Updates and Events on the Decoder/Encoder/Renderer architecture. At
the MCP boundary to LLM agents, a different mechanism is used: the
**Observer pattern**, with the hub as Subject and connected agents as
Observers, topic-based.

```text
HUB (Subject)                                     AGENTS (Observers)
─────────────                                     ──────────────────

subscription registry                             ┌──────────────────────┐
{                                                 │ Claude Code instance │
  "bead_queued":  [CC_conn, beads_dash_conn],     │ (subscribes via      │
  "modal_yes":    [CC_conn],                      │  MCP tool to         │
  "form_submit":  [CC_conn, app_x_conn],          │  bead_queued, …)     │
  …                                               └──────────┬───────────┘
}                                                            │
                                                             │ MCP tool
publish(topic, payload):                          ┌──────────▼───────────┐
  for sub in subscribers[topic]:                  │ Agent X              │
    mcp.send_notification(                        │ (subscribes to       │
      sub,
      method="observed",
      params={topic, payload})  ────────────────► 
                                                  │  form_submit only)   │
                                                  └──────────────────────┘
                                                            ▲
                                                            │ MCP notification
                                                            │ (server → client,
                                                            │  unprompted push)
                                                  ┌─────────┴────────────┐
                                                  │ Beads Dashboard      │
                                                  │ (third observer)     │
                                                  └──────────────────────┘
```

The MCP contract surface:

```text
   MCP TOOLS that agents call               MCP NOTIFICATIONS hub pushes
   ──────────────────────────              ─────────────────────────────

   subscribe(topic)                         observed(topic, payload)
   unsubscribe(topic)                         ← server → client push,
   publish(topic, payload)                    async, unprompted; the
   …existing show/update/clear…              agent runtime delivers it
                                              to the LLM, which decides

   Applet code calls hub.publish(...)        Applet code receives via
   internally; that maps to the same         Decoder if it subscribed,
   MCP publish on the wire when crossing     or via in-process delivery
   the MCP boundary.                         if the applet is in-process.
```

**Why this is loose:**

```text
   Hub knows         ─►  topic name + payload shape
                     ─►  which connections subscribed to which topics

   Hub does NOT know ─►  what observers will do with notifications
                     ─►  whether observers are LLM-driven or deterministic
                     ─►  whether there are zero observers or many

   Observer knows    ─►  the topics it cares about
                     ─►  the payload schema for those topics

   Observer does     ─►  who else is subscribed
   NOT know          ─►  what the publisher's internal state is
                     ─►  whether the publisher is an applet, the hub
                          itself, or another agent
```

This sits alongside (not in place of) the Decoder/Encoder/Renderer
families. Inside the Lux fabric, communication is shaped as state
changes (Updates) and notifications about state changes (Events). At
the MCP boundary, communication is shaped as tool calls (agent ↔ hub
RPC) and topic-based notifications (hub → agent push). The two
boundaries serve different cardinality models and trust assumptions.

## What this enables

The reason this design matters: **Lux applets and applications need real
domain behavior**, not just visual widgets that emit raw events.

A modal dialog's "OK" button isn't just a button-that-emits-click — it's
a button-that-closes-the-modal-and-passes-its-form-state-back. A draggable
window remembers its position, snaps to edges, respects monitor bounds.
A combo box maintains its selection across renders, validates new
selections against allowed values, fires change events with both old and
new values. A tree node expands and collapses, lazy-loads children,
remembers expansion state across scene replacements.

All of that is domain behavior on the Element. The renderer only knows
"the user clicked at this pixel" or "the user dropped at this position";
the Element knows what that MEANS. The decoder only knows "these bytes
came in"; the Element knows what shape it's supposed to be.

Without this design, applet authors are stuck writing event-handling
code outside the element tree, threading state through ad-hoc dicts,
re-implementing every behavior pattern in every applet. With this
design, behavior is a first-class part of every Element subclass and
composes naturally with the Composite pattern.

## Migration notes — what changes from PR 1+2

PR 1 and PR 2 shipped:

- Per-class modules with `to_dict` / `from_dict` codec methods ON the
  Element class
- A `Renderer` family of sorts (per-kind classes in `display/renderers/`)
- An `ElementRenderer` god class that dispatches by `isinstance` to the
  per-kind renderer and emits InteractionMessages directly from click
  detection

This target architecture changes:

1. **Codec moves OFF the Element class** into per-format Decoder families.
   `ButtonElement.from_dict` becomes `JsonButtonDecoder.decode`.
   `ButtonElement.to_dict` becomes `JsonButtonEncoder.encode` (if an
   Encoder family is needed for replay/inspection; otherwise drop).

2. **`render()` moves ONTO the Element class** as a template method
   inherited from the abstract `Element` base. Per-kind renderer classes
   become surface-family-scoped — `ImGuiButtonRenderer`,
   `HtmlButtonRenderer`, `RecordingButtonRenderer`. The god `ElementRenderer`
   dispatch class goes away.

3. **`renderer_factory` and `emit` are injected at Element construction.**
   Wire decode is the one place that has to thread these in — every
   other Element construction site (test code, server-side synthesis)
   already has them in scope from Display startup. Element fields gain
   these two and nothing else from the I/O concern.

4. **Behavior methods move onto Element subclasses.** `ButtonElement.on_click`,
   `WindowElement.on_minimize` / `.on_maximize` / `.on_drag`,
   `SliderElement.on_value_change`, etc. Renderers call these methods
   when the surface detects the corresponding user action; Elements
   decide what (if anything) to emit.

5. **The `ElementRenderer._RENDERERS` dispatch dict, the
   `_NATIVE_DISPATCH` tuple, and `_WIDGET_STATE_RENDERERS` propagation
   all go away.** They're replaced by the `RendererFactory.__call__`
   match-by-type dispatch in each per-surface factory.

The migration plan to get here is sequenced separately. This document is
the destination, not the route.

## Open questions

These are decided later, when first concrete need arises.

- **State invariants on patch.** When `Display.apply(SetProperty(...))`
  replaces an Element field, does the renderer need to be re-resolved?
  In the current design `renderer_factory(self)` is called on every
  render, so the answer is no — the factory looks up by type, not
  identity. But if factories ever cache per-Element renderers,
  patch-time invalidation becomes a real concern.
- **Behavior composition.** When does a button's `on_click` get
  overridden by an applet author vs. configured through a callback
  field vs. routed through an event bus? All three are common
  patterns; we should pick one default and document the others as
  legitimate variations.
- **Asynchronous behavior.** `on_click` is currently a sync method
  that calls `emit` (which queues). For applets that want to do
  async work in response to interactions, do we make `on_click`
  awaitable, dispatch through an event bus, or push the async
  concern entirely outside the Element?
- **Test renderers.** `RecordingRendererFactory` captures `(kind, id)`
  tuples; `NullRendererFactory` is a no-op. A third — an
  `EventTrackingRendererFactory` that records render calls with a
  frame counter — is useful for update-propagation tests. Build when
  needed.

## References

- [`domain-model.md`](domain-model.md) — the Element / Display / Update / Event vocabulary this builds on.
- [`x11-model.md`](x11-model.md) — the process split that runs the Display in its own process.
- [`migration-plan.md`](../oo-refactor/migration-plan.md) — the migration order.
- Gamma, Helm, Johnson, Vlissides, *Design Patterns* — Composite (the
  Element/Renderer pattern), Template Method (the `Element.render`
  template), Abstract Factory (the per-surface and per-format families).
