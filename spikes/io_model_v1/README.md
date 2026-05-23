# io-model spike v1 — minimal three-process realization

Demonstrates `docs/architecture/io-model.md` end-to-end in the smallest spec that exercises all three roundtrip kinds.

## What this spike proves

1. **Three tiers, three OS processes.** Agent, Hub, Display. Real Unix-socket IPC between them. Each tier holds its own `Display` instance with its own per-tier Element subtree decoded from incoming Updates. No shared memory.
2. **IPC carries Updates and Events. Not render calls.** Per `io-model.md` §"Where rendering happens": "No render call crosses any IPC boundary."
3. **Only the Display tier has a render loop.** Hub gets `NullRendererFactory`. Display gets the chosen surface factory. Hub never iterates its scene for drawing.
4. **Two output surfaces (selectable at Display startup).** `TextSurface` prints scenes to stdout each tick; `RecordingSurface` appends JSONL to a log file each tick. Selected via `LUX_SURFACE=text|recording` or `--surface=...`. Same Element classes, same Renderer Protocol, different per-kind renderers.
5. **Three roundtrip kinds, end-to-end:**
   - **R1 outbound + Observer push:** Agent calls `show(...)` over Lux IPC → Hub decodes + applies → encodes `AddElement` Update → ships to Display → Display decodes + applies → render loop draws. Hub publishes `scene.applied` topic → subscribed Agent receives push notification.
   - **R2 background-thread state update:** Hub timer thread mutates a `LabelElement.content` every 2s via `SetProperty` Update → Hub encodes → ships to Display → Display applies → next render shows new content.
   - **R3 user interaction roundtrip:** Display reads simulated user input from stdin (`click <button_id>`) → encodes `InteractionMessage` → ships to Hub → Hub looks up Element on its tier → `button.on_click()` runs → emits `ButtonClicked` Event → Hub publishes `interaction.<button_id>` topic → subscribed Agent receives push notification.

## Element vocabulary (smallest set that exercises Composite + behavior)

Three element kinds:

- **`LabelElement`** — leaf, no behavior. `content: str`. Background thread can mutate.
- **`ButtonElement`** — leaf, `on_click` behavior. `label: str`. User can click.
- **`PanelElement`** — composite, holds `children: tuple[Element, ...]`. No behavior of its own; renders by bracketing children.

That's one composite and two leaves, satisfying the criteria.

## Architecture (per io-model.md, verbatim)

```text
┌──────────┐   Lux IPC   ┌────────────┐   Lux IPC   ┌─────────────┐
│  Agent   │◄───────────►│    Hub     │◄───────────►│   Display   │
│ process  │             │  process   │             │   process   │
└──────────┘             └────────────┘             └─────────────┘
     │                         │                          │
     │ rf=NullRendererFactory  │ rf=NullRendererFactory   │ rf=Text or RecordingRendererFactory
     │ (no render loop)        │ (no render loop)         │ (render loop @ 10Hz)
     │                         │                          │
     │ - Subscribe to topics   │ - Subscription registry  │ - Decode inbound Updates
     │ - Send commands         │ - Background timer       │ - DisplayClient applies to display_display
     │ - Receive notifications │ - Apply Updates to       │ - Each frame: scene.render() walks tree
     │                         │   hub_display            │   and calls elem.render() through per-kind
     │                         │ - Encode Updates → ship  │   renderer (TextRenderer or RecordingRenderer)
     │                         │   to Display             │ - Stdin reader: simulated user input
     │                         │ - Decode Interactions    │
     │                         │   from Display, run      │
     │                         │   element behavior,      │
     │                         │   publish topics         │
     │                         │ - Push notifications     │
     │                         │   to subscribed Agents   │
```

Each tier decodes incoming wire payloads into its own Element tree via the Decoder family. The Hub tier and Display tier each have their own `display.apply(client_id, update)` invocations — Hub's apply produces an outbound Update via Encoder that ships to Display; Display's apply mutates the display-side tree, which the render loop draws each frame.

## Wire protocol — minimal JSON

Line-delimited JSON over Unix sockets. Each line is one envelope:

```json
{"kind": "show",          "scene_id": "...", "root": {...}}
{"kind": "add_element",   "parent": "...", "elem": {...}}
{"kind": "set_property",  "elem_id": "...", "field": "content", "value": "..."}
{"kind": "interaction",   "elem_id": "...", "action": "click"}
{"kind": "subscribe",     "topic": "scene.applied"}
{"kind": "publish",       "topic": "interaction.btn1", "payload": {...}}
```

`show` is the Agent → Hub command for "make this scene live."
`add_element` / `set_property` are Hub → Display Updates.
`interaction` is Display → Hub.
`subscribe` is Agent → Hub.
`publish` is Hub → Agent (push notification).

The Encoder family produces these payloads; the Decoder family parses them. Each per-kind Element (Label/Button/Panel) has its own `JsonLabelEncoder` / `JsonLabelDecoder` etc., registered with the Encoders/Decoders registries.

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

The Agent will:

1. Connect to Hub, subscribe to `scene.applied` and `interaction.btn1`.
2. Send `show(Panel(id=p1, children=[Label(id=lbl1, content="ticks: 0"), Button(id=btn1, label="Click me")]))`.
3. Wait for `scene.applied` push and print it.
4. Wait for `interaction.btn1` pushes (when the user clicks) and print them.

The Hub will:
1. Apply Updates from the Agent.
2. Start a background thread that increments `lbl1.content` every 2s (`SetProperty`).
3. Encode + ship Updates to Display.
4. Receive Interactions from Display → call `button.on_click()` → publish `interaction.<id>` to subscribers.

The Display will:
1. Receive Updates, decode, apply to its local tree.
2. Run a 10Hz render loop that walks the scene and calls `elem.render()`.
3. With `LUX_SURFACE=text`: prints the formatted scene each tick to stdout.
4. Read stdin; on `click btn1`, send `InteractionMessage` to Hub.

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

### Display (the domain object that holds tier-local state)

Each tier has one `Display`:

```python
class Display:
    _scene_by_id: dict[str, Element]
    _rf: RendererFactory  # injected at startup; Null on Hub, Text/Recording on Display
    _emit: Callable[[object], None]

    def apply(self, client_id: ClientId, update: Update) -> Event | None: ...
    # Hub's apply produces outbound encoded Updates via emit;
    # Display's apply mutates local state for the render loop to draw.
```

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

Tests in `tests/test_roundtrips.py`:

- **R1 outbound + Observer push.** Spawn three processes. Agent connects, subscribes to `scene.applied`, sends `show(panel_with_label_and_button)`. Within 1s, Agent receives `scene.applied` push. Display has rendered the scene at least once (Text: stdout contains "Panel", "Label", "Button"; Recording: log file contains 3 entries).
- **R2 background-thread state update.** With the scene from R1 live, wait 5s and assert the Label's content has changed at least twice (Display log shows 3+ distinct content values).
- **R3 user click roundtrip.** Send `click btn1` to Display's stdin. Within 1s, Agent receives `interaction.btn1` push notification with payload `{"elem_id": "btn1", "action": "click"}`.

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
