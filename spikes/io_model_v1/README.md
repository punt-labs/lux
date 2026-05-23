# io-model spike v1 — minimal three-process realization

Demonstrates `docs/architecture/io-model.md` end-to-end in the smallest spec that exercises all three roundtrip kinds.

## Canonical vocabulary

This spike is documentation. The verbs are precise; every log line, every demo step, every source comment uses the same words. Mixing them up makes the system harder to reason about, so they're listed up front:

| Layer | Verb | Meaning |
|---|---|---|
| **Transport** | **send / receive** | Bytes on the socket. Pure I/O, no domain meaning. |
| **Wire** | **encode / decode** | Bytes ↔ wire dict. The Encoder/Decoder families. |
| **Domain** | **instantiate** | Build a tier-local `Element` object from a decoded wire dict via the per-kind Decoder. The injected `renderer_factory` distinguishes the tier (Null on Hub/AGNT, Surface on DISP). |
| | **accept** | Hub commits a state change to `hub_display`. After accept, the Hub is authoritative. The Hub is the **only** tier that accepts. |
| | **apply** | DISP mirrors an accepted Update into `display_display`. The Hub remains authoritative; DISP holds a local copy for its render loop. |
| | **resolve** | Look up an `Element` by id on the tier's local state. |
| | **invoke** | Call a behavior method on a resolved `Element` (e.g. `button.on_click()`). |
| | **emit** | A behavior method produces a domain `Event` (e.g. `ButtonClicked`). |
| | **publish** | Hub fans an Event out to topic subscribers as `observed` envelopes. |
| | **notify** | A subscriber's local handler runs for an `observed` Event. |
| **Surface** | **render** | DISP walks `display_display` and paints the surface. The **only** tier that renders. |
| **Origin** | **detect** | DISP recognizes a user input event. The **only** tier where user input enters the system. |

## What this spike proves

1. **Three tiers, three OS processes.** Agent, Hub, Display. Real Unix-socket IPC between them. Each tier holds its own `Display` instance with its own per-tier Element subtree (instantiated from decoded wire dicts). No shared memory.
2. **IPC carries Updates and Events. Not render calls.** Per `io-model.md` §"Where rendering happens": "No render call crosses any IPC boundary."
3. **Hub accepts; DISP mirrors and renders.** Hub gets `NullRendererFactory` and has no render loop — its role is to accept and propagate. DISP gets the chosen surface factory and runs the render loop. AGNT is a pure subscriber/sender.
4. **Two output surfaces (selectable at DISP startup).** `TextSurface` prints scenes to stdout each tick; `RecordingSurface` appends JSONL to a log file each tick. Selected via `LUX_SURFACE=text|recording`. Same Element classes, same Renderer Protocol, different per-kind renderers.
5. **Four roundtrip kinds, end-to-end:**
   - **R1 — show + accept + apply + render + notify.** AGNT subscribes to `scene.accepted`, then sends `show(Panel{Label, Button})` to HUB. HUB decodes + instantiates Hub-tier Elements (rf=Null), accepts the scene on `hub_display`, encodes + sends an `AddElement` Update to DISP, and publishes `scene.accepted`. DISP receives + decodes + instantiates DISP-tier Elements (rf=Surface), applies the Update to `display_display`, and renders each frame. AGNT is notified via push.
   - **R2 — background-thread accept + apply + render.** HUB's timer thread is an in-process source of authoritative state changes: each tick it accepts a `SetProperty` Update on `hub_display`, then encodes + sends to DISP. DISP applies the Update to `display_display`; the next frame renders the new content.
   - **R3 — detect + send + resolve + invoke + emit + publish + notify.** USER produces a keystroke on DISP. DISP detects the click, encodes an `InteractionMessage`, and sends to HUB. HUB receives + decodes, resolves the Element on `hub_display`, invokes `button.on_click()`, which emits a `ButtonClicked` Event. HUB publishes `interaction.<id>` to subscribers. AGNT (subscribed) is notified.
   - **R4 — interactive dialog with scene replacement.** AGNT (in `dialog` mode) shows a Yes/No confirmation: `Panel{Label("Save your work?"), Button("Yes"), Button("No")}`. USER clicks Yes. R3's inbound roundtrip carries the click to AGNT, which reacts: performs a short computation and sends a NEW `show()` for a result scene `Panel{Label("Saved."), Label("Result: ...")}`. HUB accepts the new scene — because the new root has `parent_id=None`, both `hub_display` and `display_display` PRUNE the old scene's indices before installing the new tree (whole-scene replacement). DISP renders the result; the dialog is gone. AGNT is notified of `scene.accepted` for the new scene. This proves the full agent-in-the-loop cycle: user input → agent reaction → new scene → display update.

## Element vocabulary (smallest set that exercises Composite + behavior)

Three element kinds:

- **`LabelElement`** — leaf, no behavior. `content: str`. Background thread can mutate.
- **`ButtonElement`** — leaf, `on_click` behavior. `label: str`. User can click.
- **`PanelElement`** — composite, holds `children: tuple[Element, ...]`. No behavior of its own; renders by bracketing children.

That's one composite and two leaves, satisfying the criteria.

## Architecture (per io-model.md)

```text
┌──────────┐   Lux IPC   ┌────────────┐   Lux IPC   ┌─────────────┐
│  AGNT    │◄───────────►│    HUB     │◄───────────►│    DISP     │
│ process  │             │  process   │             │   process   │
└──────────┘             └────────────┘             └─────────────┘
     │                         │                          │
     │ rf=NullRendererFactory  │ rf=NullRendererFactory   │ rf=Text or RecordingRendererFactory
     │ (no render loop)        │ (no render loop)         │ (render loop @ N Hz)
     │                         │                          │
     │ subscribe(topic)        │ SUBSCRIPTION REGISTRY    │ RECEIVE Updates from HUB
     │ send commands           │   subscribe / publish    │ DECODE + INSTANTIATE DISP-tier Elements
     │ receive observed{}      │                          │   (rf=Surface)
     │ NOTIFY local handler    │ AUTHORITATIVE STATE      │ APPLY Updates → display_display
     │                         │   hub_display            │   (mirrors Hub state)
     │                         │                          │
     │                         │ inbound from AGNT:       │ RENDER LOOP each frame:
     │                         │   DECODE + INSTANTIATE   │   walk display_display,
     │                         │   ACCEPT scene/property  │   call elem.render()
     │                         │   on hub_display         │   → surface paints
     │                         │   ENCODE + SEND Update   │
     │                         │   to DISP                │ USER-INPUT DETECTOR (stdin):
     │                         │   PUBLISH 'scene.…'      │   DETECT click
     │                         │                          │   ENCODE InteractionMessage
     │                         │ background TIMER:        │   SEND to HUB
     │                         │   accepts SetProperty    │
     │                         │   per tick               │
     │                         │                          │
     │                         │ inbound from DISP:       │
     │                         │   DECODE Interaction     │
     │                         │   RESOLVE Element by id  │
     │                         │   INVOKE on_click()      │
     │                         │   on_click() EMITS Event │
     │                         │   PUBLISH 'interaction.…'│
```

Note the **role asymmetry** between Hub and DISP. Hub `accepts`; DISP `applies`. The state-mutation primitive is the same — both end up updating their tier-local `Display` object — but the role differs: Hub commits (it is the source of truth), DISP mirrors. Naming the methods `accept` vs `apply` keeps the boundary explicit.

## Wire protocol — minimal JSON

Line-delimited JSON over Unix sockets. Each line is one envelope:

```json
{"kind": "show",          "scene_id": "...", "root": {...}}
{"kind": "add_element",   "scene_id": "...", "parent_id": null, "elem": {...}}
{"kind": "set_property",  "elem_id": "...", "field": "content", "value": "..."}
{"kind": "interaction",   "elem_id": "...", "action": "click"}
{"kind": "subscribe",     "topic": "scene.accepted"}
{"kind": "observed",      "topic": "interaction.btn1", "payload": {...}}
```

Per-direction summary:

- **AGNT → HUB:** `show`, `subscribe`.
- **HUB → DISP:** `add_element`, `set_property` (the Update family).
- **DISP → HUB:** `interaction`.
- **HUB → AGNT:** `observed` (the push notification carrying the published topic payload).

The Encoder family produces these payloads; the Decoder family parses them. Each per-kind Element (Label/Button/Panel) has its own `JsonLabelEncoder` / `JsonLabelDecoder` etc., registered with the `JsonEncoderFactory` / `JsonElementFactory` registries.

## Module layout

```text
spikes/io_model_v1/
├── README.md                       (this spec)
├── pyproject.toml                  (uv project; scripts: lux-spike-{hub,display,agent})
├── src/lux_spike/
│   ├── __init__.py
│   ├── element.py                  (Element ABC with template-method render() + _children())
│   ├── protocols.py                (Renderer, RendererFactory, Decoder, Encoder Protocols)
│   ├── updates.py                  (Update sum: AddElement, SetProperty.  Event sum: ButtonClicked, PropertyChanged.  InteractionMessage.)
│   ├── elements.py                 (LabelElement, ButtonElement, PanelElement)
│   ├── codec.py                    (JsonDecoder, JsonEncoder per kind + registries)
│   ├── connection.py               (Unix-socket Connection, line-delimited framing)
│   ├── renderers/
│   │   ├── __init__.py
│   │   ├── null.py                 (NullRenderer + NullRendererFactory — used on Hub and Agent tiers)
│   │   ├── text.py                 (TextLabel/Button/PanelRenderer + TextRendererFactory)
│   │   └── recording.py            (RecordingLabel/Button/PanelRenderer + RecordingRendererFactory)
│   ├── hub.py                      (hub process entry — registry, timer thread, Update encoding, Observer push)
│   ├── display.py                  (display process entry — DisplayClient, render loop, stdin user-input thread)
│   └── agent.py                    (agent process entry — show() command, subscribe(), notification handler)
└── tests/
    ├── conftest.py                 (spawn all three processes for a test, tear down cleanly)
    └── test_roundtrips.py          (R1 + R2 + R3 end-to-end assertions)
```

Aim: every module ≤ 150 lines. The spike is intentionally small.

## Run sequence

Three terminals:

```bash
# Terminal 1: Hub
LUX_SPIKE_HUB_AGENT_SOCK=/tmp/lux-spike-agent.sock LUX_SPIKE_HUB_DISPLAY_SOCK=/tmp/lux-spike-display.sock lux-spike-hub

# Terminal 2: Display (with TextSurface — prints each tick to stdout)
LUX_SURFACE=text LUX_SPIKE_HUB_DISPLAY_SOCK=/tmp/lux-spike-display.sock lux-spike-display

# Terminal 3: Agent
LUX_SPIKE_HUB_AGENT_SOCK=/tmp/lux-spike-agent.sock lux-spike-agent
```

The AGNT will:

1. Connect to HUB, subscribe to `scene.accepted` and `interaction.btn1`.
2. Send `show(Panel(id=p1, children=[Label(id=lbl1, content="ticks: 0"), Button(id=btn1, label="Click me")]))`.
3. Be notified for `scene.accepted` and `interaction.btn1` topics (handler runs, prints the observed envelope).

The HUB will:

1. Decode + instantiate Hub-tier Elements from inbound `show` commands (rf=Null).
2. Accept the resulting scene on `hub_display`.
3. Encode + send the `AddElement` Update to DISP.
4. Publish `scene.accepted` to subscribers.
5. Run a background timer that accepts a `SetProperty(content='ticks: N')` on `hub_display` every N seconds, then encodes + sends to DISP.
6. Receive `InteractionMessage`s from DISP, resolve the Element on `hub_display`, invoke the behavior method, and publish the emitted Event to the matching `interaction.<id>` topic.

The DISP will:

1. Receive Updates from HUB, decode + instantiate DISP-tier Elements (rf=Surface), apply to `display_display`.
2. Run a render loop at `LUX_SPIKE_DISPLAY_HZ` Hz that walks `display_display` each frame and calls `elem.render()`. With `LUX_SURFACE=text` it prints; with `LUX_SURFACE=recording` it appends JSONL.
3. Detect user input from stdin (`click <elem_id>`), encode an `InteractionMessage`, and send to HUB.

Run with `LUX_SURFACE=recording` to see scenes written to `/tmp/lux-spike-recording.jsonl` instead of stdout.

## Class signatures (the contract)

### Element ABC

```python
class Element(ABC):
    _renderer_factory: RendererFactory
    _emit: Callable[[object], None]

    def __new__(cls, *, renderer_factory, emit, **kwargs) -> Self: ...
    def render(self) -> None:
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
        return ()
```

### Renderer Protocol

```python
@runtime_checkable
class Renderer(Protocol):
    def render(self) -> None: ...           # leaf
    def begin(self) -> None: ...            # composite
    def end(self) -> None: ...              # composite

@runtime_checkable
class RendererFactory(Protocol):
    def __call__(self, elem: Element) -> Renderer: ...
```

### Element kinds

```python
class LabelElement(Element):
    _id: str
    _content: str
    # leaf; no behavior

class ButtonElement(Element):
    _id: str
    _label: str
    # leaf; behavior:
    def on_click(self) -> None:
        self._emit(ButtonClicked(elem_id=self._id))

class PanelElement(Element):
    _id: str
    _children_tuple: tuple[Element, ...]
    def _children(self) -> tuple[Element, ...]:
        return self._children_tuple
```

### Updates / Events / Interaction

```python
@dataclass(frozen=True, slots=True)
class AddElement:
    scene_id: str
    elem: Element  # or wire dict pre-decode

@dataclass(frozen=True, slots=True)
class SetProperty:
    elem_id: str
    field: str
    value: object  # str for content, etc.

@dataclass(frozen=True, slots=True)
class ButtonClicked:
    elem_id: str

@dataclass(frozen=True, slots=True)
class InteractionMessage:
    elem_id: str
    action: str  # "click"
```

### Tier-local Display (state owner)

Each tier has one `Display`-shaped state owner. The verb differs by role:

```python
class HubDisplay:
    """Authoritative state. `accept(update)` commits the change; after
    accept, hub_display reflects the new authoritative state."""

    _by_id: dict[str, Element]
    _root_id: str | None

    def accept(self, update: AddElement | SetProperty) -> None: ...
    def resolve(self, elem_id: str) -> Element | None: ...

class DisplayDisplay:
    """Local mirror of Hub state. `apply(update)` mirrors an accepted
    Update into display_display; the render loop reads from here."""

    _by_id: dict[str, Element]
    _root: Element | None

    def apply(self, update: AddElement | SetProperty) -> None: ...
```

The state-mutation primitive is identical (index by id, mutate fields). The role differs: Hub **accepts** (it is the source of truth), DISP **applies** (it mirrors).

### Hub-tier renderers (Null)

```python
class NullRenderer:
    def render(self) -> None: pass
    def begin(self) -> None: pass
    def end(self) -> None: pass

class NullRendererFactory:
    def __call__(self, elem: Element) -> Renderer:
        return _NULL  # singleton
```

### Display-tier renderers (Text — one per element kind)

```python
class TextLabelRenderer:
    _elem: LabelElement
    _out: TextOutput
    def render(self) -> None:
        self._out.line(f"  Label[{self._elem._id}]: {self._elem._content}")

class TextButtonRenderer:
    _elem: ButtonElement
    _out: TextOutput
    def render(self) -> None:
        self._out.line(f"  Button[{self._elem._id}]: [{self._elem._label}]")

class TextPanelRenderer:
    _elem: PanelElement
    _out: TextOutput
    def begin(self) -> None:
        self._out.line(f"Panel[{self._elem._id}]:")
    def end(self) -> None:
        self._out.line("")

class TextRendererFactory:
    _out: TextOutput
    def __call__(self, elem: Element) -> Renderer:
        match elem:
            case LabelElement():   return TextLabelRenderer(elem, self._out)
            case ButtonElement():  return TextButtonRenderer(elem, self._out)
            case PanelElement():   return TextPanelRenderer(elem, self._out)
```

### Display-tier renderers (Recording — same shape, different surface)

```python
class RecordingLabelRenderer:
    _elem: LabelElement
    _log: RecordingLog
    def render(self) -> None:
        self._log.append({"kind": "label", "id": self._elem._id, "content": self._elem._content})

# etc.
```

Each surface (`TextOutput`, `RecordingLog`) is a small composed object — the factory holds it, per-kind renderers receive it via constructor. No god class on either surface.

## Acceptance criteria

Tests in `tests/test_roundtrips.py`. Each test spawns its own trio of processes; no state leaks between tests.

- **R1 — show + accept + apply + render + notify.** AGNT subscribes to `scene.accepted`, sends `show(Panel{Label, Button})`. HUB accepts the scene on `hub_display`, sends `AddElement` to DISP, publishes `scene.accepted`. DISP applies + renders. AGNT is notified. Recording surface shows at least 4 entries (Panel begin + Label + Button + Panel end).
- **R2 — background-thread accept + apply + render.** HUB timer accepts a `SetProperty(content='ticks: N')` every tick. DISP applies + renders; assert ≥ 4 distinct `ticks: N` values appear in the recording log.
- **R3 — detect + send + resolve + invoke + emit + publish + notify.** Inject a click via the test-only `synthesize_interaction` agent command (equivalent to DISP receiving stdin `click btn1` and sending the `InteractionMessage`). Assert AGNT receives the `interaction.btn1` push with payload `{"elem_id": "btn1"}`.
- **R4 — interactive dialog with scene replacement.** AGNT runs in `dialog` mode (sends a Yes/No dialog, reacts to clicks by sending a new scene). Wait for the dialog to render on DISP. Inject a click on `btn_yes`. AGNT receives the push, performs its computation, sends `show(result_scene)`. Assert the result scene's elements appear in the recording log AND the dialog's elements do not appear in any entry after the result scene takes over (proves whole-scene replacement pruned the old indices). Assert AGNT received the `interaction.btn_yes` push.

The `demo.py` script runs the same four scenarios with full tier-tagged narration, each verified by per-step `require()` calls that wait for the expected log lines from each tier.

## Agent modes

The AGNT process supports two modes selected via `LUX_SPIKE_AGENT_MODE`:

- **`basic`** (default) — sends a single `show(Panel{Label, Button})` and waits. Used by R1, R2, R3.
- **`dialog`** — sends a Yes/No dialog. The notification handler reacts to `interaction.btn_yes` / `interaction.btn_no` pushes by composing a new scene (result / cancellation) and sending it via `show()`. The new scene REPLACES the dialog (the wire-level mechanic is `AddElement` with `parent_id=None`, which triggers HubDisplay.accept's whole-scene-replace path). Used by R4.

Both modes are in `src/lux_spike/agent.py` as separate functions (`_basic_mode`, `_dialog_mode`). The dialog mode is a worked example of "agent observes a click, performs work, ships new scene" — the foundational interactive loop for any Lux applet that needs to respond to user input.

Each test asserts:
- Three processes spawned successfully.
- Unix sockets created.
- Each process holds its own `Display` instance.
- Wire payloads are Updates/Events/Interactions — never render calls.

## Out of scope (explicitly)

- ImGui rendering (use TextSurface + RecordingSurface instead).
- MCP protocol (use a thin Unix-socket JSON-line protocol).
- The full Encoder family beyond JSON (one format only).
- Per-connection format negotiation.
- Subprocess supervision / crash recovery.
- Authentication on sockets.
- Multi-agent (one agent at a time).
- Performance budgets.
- The 24-element-kind catalogue (three kinds only).

This is a spike. It demonstrates the io-model architecture works end-to-end. It is not production code.
