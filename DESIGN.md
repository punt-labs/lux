# Lux Design Decision Log

This file is the authoritative record of design decisions, prior approaches, and their outcomes. **Every design change must be logged here before implementation.**

## Rules

1. Before proposing ANY design change, consult this log for prior decisions on the same topic.
2. Do not revisit a settled decision without new evidence.
3. Log the decision, alternatives considered, and outcome.

---

## System Architecture

```text
Claude Code                                          Lux Display (ImGui)
                                                     ┌──────────────────────┐
┌───────────────────────┐                            │                      │
│  LLM (Claude)         │                            │  ImGui Render Loop   │
│  "show a diagram with │                            │  (60fps)             │
│   Approve/Deny"       │                            │                      │
└──────────┬────────────┘                            │  ┌────────────────┐  │
           │                                         │  │ Scene Renderer │  │
           │ MCP tool call                           │  │ (dispatch table│  │
           ▼                                         │  │  JSON → ImGui) │  │
┌──────────────────────┐    Unix domain socket       │  └───────▲────────┘  │
│  lux.show(scene)     │    (length-prefixed JSON)   │          │           │
│  lux.update(patches) ├────────────────────────────►│  FrameReader         │
│  lux.clear()         │                             │  select() per frame  │
│                      │◄────────────────────────────┤                      │
│  receives:           │    interaction events        │  ┌────────────────┐  │
│  - button clicks     │    window lifecycle          │  │ Texture Cache  │  │
│  - slider changes    │                             │  │ (GPU upload)   │  │
│  - text input        │                             │  └────────────────┘  │
│  - window closed     │                             │                      │
└──────────────────────┘                             │  ┌────────────────┐  │
                                                     │  │ Code Runner    │  │
  MCP Server (punt-lux)                              │  │ (opt-in, user  │  │
  stdio transport                                    │  │  consent gate) │  │
  spawned by Claude Code                             │  └────────────────┘  │
                                                     └──────────────────────┘
                                                       Persistent process
                                                       lux display
```

### Key Interactions

#### 1. Show an Image with Action Buttons

```text
LLM            MCP Tool         Socket           Display          User
 │              (lux.show)                        (ImGui)
 │  "show img   │                │                │                │
 │   + buttons" │                │                │                │
 ├─────────────►│  scene JSON    │                │                │
 │              ├───────────────►│                │                │
 │              │                │  render scene  │                │
 │              │                ├───────────────►│  image +       │
 │              │                │                │  buttons       │
 │              │                │   ack          │  visible       │
 │              │                │◄───────────────┤                │
 │              │                │                │  clicks        │
 │              │                │  interaction   │  "Approve"     │
 │              │                │◄───────────────┤◄───────────────┤
 │              │◄───────────────┤                │                │
 │  "user       │                │                │                │
 │   approved"  │                │                │                │
 │◄─────────────┤                │                │                │
```

#### 2. Code-on-Demand (Game in Canvas)

```text
LLM            MCP Tool         Socket           Display          User
 │              (lux.show)                        (ImGui)
 │  render_fn   │                │                │                │
 │  element     │                │                │                │
 ├─────────────►│  scene with    │                │                │
 │              │  kind:         │                │                │
 │              │  render_fn     │                │                │
 │              ├───────────────►│                │                │
 │              │                │  consent modal │                │
 │              │                ├───────────────►│  "Claude wants │
 │              │                │                │   to run code" │
 │              │                │                │  [Allow] [Deny]│
 │              │                │                │◄───────────────┤
 │              │                │                │  clicks Allow  │
 │              │                │  run render    │                │
 │              │                │  function each │  game running  │
 │              │                │  frame         │  in canvas     │
 │              │                │                │                │
 │              │                │  interaction   │  game_over     │
 │              │                │◄───────────────┤  event         │
 │              │◄───────────────┤                │                │
 │  "game over, │                │                │                │
 │   score: 42" │                │                │                │
 │◄─────────────┤                │                │                │
```

---

## DES-001: Rendering Toolkit — ImGui via imgui-bundle

**Date:** 2026-03-06
**Status:** SETTLED
**Topic:** Which GUI toolkit renders the Lux display surface

### Design

Use **Dear ImGui** via the **imgui-bundle** Python package (pip: `imgui-bundle`). The display process is a persistent ImGui application (`lux display`) that renders content driven by an external client (the MCP server).

### Spike Findings (Spike A)

- imgui-bundle 1.92.600 has pre-built wheels for macOS ARM64 (10.6 MB), Linux x86-64/ARM64, Windows. Python 3.11-3.14.
- API: `immapp.run()` for the event loop, `hello_imgui.RunnerParams` for lifecycle hooks, `imgui.image()` for textures.
- Image display requires OpenGL texture upload (~10 lines via PyOpenGL). `ImTextureRef` wrapper required (not raw int).
- Immediate mode is ideal for LLM-driven UI: `show_gui` callback redraws every frame, layouts change freely.
- All ImGui calls must happen on the main thread (standard for GUI frameworks).

### Why ImGui Over Qt

The LLM is the window manager. The UI is LLM-generated content that changes every frame — not a fixed application shell. ImGui's immediate mode means "just describe what you want this frame" — no widget lifecycle, no tree diffing, no cleanup. Qt's retained-mode widget hierarchy would fight this model.

Additionally, ImGui imposes no structural paradigm. The LLM can compose novel UI elements — custom overlays, annotations drawn on images, mixed layouts — all as draw calls. It's a canvas in the truest sense.

### Why imgui-bundle Over pyimgui

imgui-bundle bundles window management, backend abstraction (SDL/GLFW), and 21 extension libraries (ImPlot, node editor, markdown renderer, code editor, etc.). pyimgui requires wiring all of this yourself. imgui-bundle is strictly better for this use case.

### Rejected: Qt (PySide6)

Qt has native widgets, accessibility, and mature Python bindings. But:

- Retained-mode widget lifecycle is wrong for LLM-driven UI (create, update, destroy objects).
- 100MB+ dependency vs 10.6MB.
- The LLM would be constrained to pre-designed widget arrangements rather than composing freely.

### Rejected: SwiftUI + Unix Socket

Native, beautiful on macOS, but macOS-only. Cross-platform is a hard requirement.

### Rejected: SDL3 + Custom Rendering

Cross-platform but requires building every widget from scratch. ImGui already solves this.

### Rejected: Terminal Graphics Protocols (Kitty/iTerm2/Sixel)

No interactivity — terminal owns input, no click events on placed images. Lux needs clickable buttons and interactive controls.

---

## DES-002: IPC — Unix Domain Socket with select() Polling

**Date:** 2026-03-06
**Status:** SETTLED
**Topic:** How the MCP server communicates with the display process

### Design

Unix domain socket (`AF_UNIX`, `SOCK_STREAM`) with 4-byte big-endian length-prefixed JSON framing. The display process polls the socket via `select()` with zero timeout once per frame in the render loop. Bidirectional: client sends content, display sends events back.

### Spike Findings (Spike B)

Measured on macOS, Python stdlib:

- Content update ack (burst): ~10ms median
- Ping-pong RTT: ~21ms median
- Click event RTT: ~20ms median
- 100 rapid burst messages: zero drops
- The 16ms floor is inherent to 60fps polling — well below human perception threshold.

### Why This Design

- **Stream sockets** provide backpressure (datagrams can silently drop).
- **Bidirectional** on one connection (named pipes cannot do this).
- **Works identically** on macOS and Linux.
- **No threads, no asyncio** — `select()` once per frame is the simplest correct architecture. Threading adds complexity without benefit since polling is inherently frame-rate-limited.
- **Pairs with ImGui's main-thread constraint** — everything runs on one thread.

### Socket Discovery

```text
$XDG_RUNTIME_DIR/lux/display.sock      (preferred, per XDG spec)
/tmp/lux-$USER/display.sock             (fallback)
LUX_SOCKET env var                      (override)
```

### Rejected: Shared Memory + Signaling

Over-engineered. The 16ms frame loop is the bottleneck, not kernel IPC overhead. JSON over a local socket is fast enough.

### Rejected: Named Pipes (FIFO)

Unidirectional. Would need two pipes for bidirectional communication. More complex, no benefit.

### Rejected: Threading (Socket Reader Thread + Queue)

Adds complexity (locks, queue synchronization) without benefit. The render loop's frame rate is the natural polling cadence.

### Rejected: asyncio Integration

Mixing asyncio with ImGui's render loop requires custom event loop integration. `select()` is simpler and sufficient.

---

## DES-003: Display Protocol — Declarative JSON Scenes

**Date:** 2026-03-06
**Status:** SETTLED
**Topic:** Message format between MCP server and display

### Design

JSON messages with typed envelopes (`type` field). Declarative scene graph — the LLM says "what should be on screen," not "how to draw it." The display interprets the scene each frame.

### Wire Format

4-byte big-endian unsigned integer (payload length) followed by UTF-8 JSON payload. Maximum 16 MiB per message.

### Client-to-Display Messages

| Type | Purpose |
|------|---------|
| `scene` | Replace entire display contents. Elements + layout. |
| `update` | Patch specific elements by ID without full redraw. |
| `clear` | Remove all content. |
| `ping` | Heartbeat / latency measurement. |

### Display-to-Client Messages

| Type | Purpose |
|------|---------|
| `ready` | Sent once after init. Protocol version + capabilities. |
| `ack` | Acknowledges scene/update. May contain error. |
| `interaction` | User interacted with an element (click, value change). |
| `window` | Lifecycle: resized, closed, focused, unfocused. |
| `pong` | Response to ping. |

### Element Types

Elements have a `kind` field. Four layout modes: `single`, `rows`, `columns`, `grid`.

See `spikes/c-protocol-design/PROTOCOL.md` for full field-level specification and `EXAMPLES.md` for concrete message flows.

### Why Declarative Over Imperative

LLMs think in "what to show," not "how to draw." A declarative scene is a JSON document the LLM can construct directly. No widget lifecycle, no draw-call ordering concerns, no cleanup. The conversion from scene to ImGui calls is a stateless function in the display's render loop.

### Why JSON

Human-readable, LLM-native (LLMs already produce JSON fluently), debuggable (pipe through `jq`). Performance is not the bottleneck over a local Unix socket. MessagePack or protobuf would add a build step and hurt debuggability for negligible performance gain.

### Extensibility

Unknown `type` values silently ignored. Unknown fields within known types silently ignored. New element kinds addable without breaking old implementations.

### Rejected: Binary Protocol (Protobuf/MessagePack)

Adds build step, hurts debuggability, and LLMs cannot construct binary messages natively. JSON is fast enough for local IPC.

### Rejected: Imperative Draw Commands

"Draw a circle at (x,y)" requires the LLM to manage draw ordering, clipping, state. Declarative scenes let the LLM think at a higher level. (Note: the `draw` element kind provides escape-hatch access to ImDrawList primitives within the declarative model.)

---

## DES-004: Rendering Posture — Full JSON Vocabulary + Opt-In Code Running

**Date:** 2026-03-06
**Status:** SETTLED
**Topic:** How much control Claude has over the display surface

### Design

Two rendering layers:

1. **Declarative JSON vocabulary (default)** — Every ImGui primitive is mapped to a JSON element kind. Claude constructs scenes from these. The display has a hardcoded dispatch table: `kind` to ImGui calls. Safe by construction — Claude can only do what the dispatch table allows. This is the paintbrush.

2. **Code-on-demand (opt-in, user consent)** — A `kind: "render_function"` element containing Python source code. The display shows the code to the user in a consent modal (inside ImGui). If allowed, the code is compiled once and called each frame. Follows the same permission model as Claude Code's Bash tool.

### Why This Split

The declarative vocabulary covers the common cases: images, text, buttons, sliders, tables, plots, diagrams (via draw commands). It is safe because the dispatch table is the sandbox — no arbitrary code.

But some use cases (games, complex animations, novel visualizations) cannot be expressed declaratively. They need loops, conditionals, and state management between ImGui calls. The code-on-demand path handles these, gated by explicit user consent.

### The Consent Mechanism (Spike E)

- Modal ImGui window: "Claude wants to run custom code"
- Scrollable code view with line numbers
- AST warning scanner flags suspicious patterns (imports of `os`, `subprocess`, calls to `open()`) — shown in yellow. Not a security boundary, just a user-facing signal.
- Allow / Deny buttons
- If allowed: code compiled once, `render(ctx)` called each frame
- `RenderContext` provides: state dict (persistent), dt, frame counter, dimensions, event sender
- Errors caught per-frame, displayed in-window in red
- Hot-reload: new code triggers new consent prompt

### Spike Findings (Spike E)

- Running compiled code inside ImGui's render loop works smoothly. No measurable performance overhead vs normal function calls (compile happens once, per-frame call is equivalent to a function call).
- Consent UX feels natural in ImGui — modal dialogs are first-class.
- Error display in-window is effective — user sees the traceback without the window crashing.
- Hot-reload works: new code replaces old, state optionally preserved.
- Bouncing ball animation, click-the-target game, and consent flow all demonstrated working.

### Python Has No Real Sandbox

There is no reliable in-process Python sandbox. `RestrictedPython` can be bypassed. PyPy sandbox is abandoned. `seccomp` is Linux-only. The honest security model is: the user consents to run the code, just like they consent to Claude running Bash commands. The AST check is a warning layer, not a security boundary.

### Why Not Code-Only (No Declarative Layer)

Most interactions do not need arbitrary code. An image with two buttons does not justify running code. The declarative layer is simpler to construct (JSON), safer (no running of code), and sufficient for the 80% case. Code-on-demand is the escape hatch, not the default.

### Why Not Declarative-Only (No Code)

Games, complex animations, and novel visualizations cannot be expressed as static JSON scenes. The LLM needs loops, conditionals, and per-frame state management. Constraining to declarative-only would make Lux an image viewer with buttons, not a paintbrush.

---

## DES-005: Element Vocabulary — Full ImGui Primitive Coverage

**Date:** 2026-03-06
**Status:** IN PROGRESS
**Topic:** Which ImGui primitives are exposed as JSON element kinds

### Design

The JSON vocabulary maps ImGui's ~250 primitives into categorized element kinds. The goal is full coverage — Claude should be able to use any ImGui capability through JSON, with code-on-demand as the escape hatch for truly custom rendering.

### Categories

**Display elements** (output only):

- `text` — with styles: heading, body, caption, code, colored
- `image` — PNG/JPEG by file path or base64 inline
- `markdown` — rendered via imgui_md extension
- `separator` — horizontal divider, optionally with label
- `progress` — progress bar with label
- `spinner` — loading indicator

**Interactive elements** (generate events back):

- `button` — standard, small, arrow, image variants
- `checkbox` — boolean toggle
- `slider` — float or int with range
- `input_text` — single-line or multiline
- `combo` — dropdown selection
- `radio` — radio button group
- `color_picker` — color selection
- `selectable` — clickable item in a list

**Data display elements**:

- `table` — rows, columns, headers, sortable
- `plot` — wraps ImPlot: line, scatter, bar, heatmap (data as arrays)
- `tree` — collapsible tree nodes

**Drawing elements** (ImDrawList):

- `draw` — list of draw commands: line, rect, circle, triangle, bezier, text, polyline. This is the low-level paintbrush within the declarative model.

**Layout elements**:

- `group` — wraps children with layout (rows, columns, grid)
- `tab_bar` — tabbed sections
- `collapsing_header` — collapsible section

**Code path**:

- `render_function` — Python source code, gated by user consent (DES-004)

### State Management for Interactive Elements

ImGui requires persistent state for inputs (slider values, checkbox states, text buffers). The display maintains a state dict keyed by element ID. When an interactive element appears in a scene, the display:

1. Initializes state from the element's `value` field (if present)
2. On user interaction, updates the local state and sends an `interaction` event
3. On subsequent scenes, the element's `value` field overrides the local state (client is authoritative)

### Status

Spike D (in progress) is implementing the renderer/dispatch table and building working demos for: diagrams (draw commands), interactive control panels, and data display (tables + plots).

---

## DES-006: Window Behavior

**Date:** 2026-03-06
**Status:** SETTLED
**Topic:** Display window positioning and behavior

### Design

- **Always-on-top**: Supported via ImGui/SDL window hint. Enabled by default, toggleable.
- **Floating**: The window floats independently. It remembers its last position across sessions.
- **No terminal docking**: There is no standard OS API to attach a window to a terminal. Terminal-proximity positioning (detecting terminal window bounds via accessibility APIs) is a future enhancement, not v0.1.

### Why Not Dock to Terminal

Docking requires OS-specific accessibility APIs (macOS `CGWindow`, Linux `xdotool`/Sway IPC) and varies by terminal emulator. The complexity is not justified for v0.1. A floating always-on-top window that remembers its position is sufficient.

---

## DES-007: Image Generation Backend — OpenAI

**Date:** 2026-03-06
**Status:** SETTLED (for v0.1)
**Topic:** Which image generation provider to use initially

### Design

OpenAI image generation (DALL-E 3 or gpt-image-1) as the first backend. API key available. May be slow but acceptable for initial development.

### Future

Multi-provider support following the same pattern as Vox (which supports ElevenLabs, OpenAI, AWS Polly, macOS say, espeak-ng). Lux will support swapping providers without changing calling code.

---

## DES-008: Cross-Platform Requirement

**Date:** 2026-03-06
**Status:** SETTLED
**Topic:** Platform support scope

### Design

Lux must work on macOS and Linux. Windows is a bonus if free (imgui-bundle has Windows wheels). This requirement eliminated SwiftUI (macOS-only) and terminal graphics protocols (terminal-dependent).

### Why

Punt Labs tools target developers and AI agents working in terminals. macOS and Linux cover the primary user base. Windows support is nice-to-have but not a blocking requirement.

---

## DES-009: Z Specification — ProB Animatability Constraints

**Date:** 2026-03-07
**Status:** SETTLED
**Topic:** How to write Z specifications that ProB can animate and model-check

### Context

The display server has a formal Z specification (`docs/display-server.tex`) type-checked with fuzz and model-checked with ProB. Getting a fuzz-valid spec to also work in ProB required several structural changes. These lessons apply to all future Z specs in this project.

### Constraint 1: Single Flat State Schema

ProB merges all state schemas into one B machine. The `Init` schema must set **all** state variables from **all** schemas. If you have separate state schemas (e.g., `FrameReaderState` and `DisplayServer`), either:

- Merge them into one schema (preferred), or
- Ensure `Init` explicitly declares and assigns every variable from every schema

ProB's heuristic: it looks for a schema named exactly `Init` whose declaration part includes exactly one schema reference (`State'`). If Init doesn't cover all state variables, ProB won't recognize it as the initialization.

### Constraint 2: No Schema Types as Values

ProB cannot handle schema types as function ranges or record values. This means:

- **Bad**: `currentScene : Scene` where `Scene` is a schema
- **Bad**: `readers : FD \pfun FrameReaderState`
- **Good**: Flatten schema fields directly into the state (`sceneId : SCENEID`, `elemIds : \power ELEMID`, etc.)

Schema types are fine for documentation and fuzz type-checking, but the state schema must use only basic types, given sets, free types, powersets, and partial functions over those.

### Constraint 3: Avoid `\seq` — Use `\power` Instead

`\seq T` translates to `1..n \tfun T` in B, which is an infinite type (sequences of any length). ProB must enumerate all possible lengths, causing unbounded enumeration even with `MAXINT` set. In contrast, `\power T` is a finite powerset bounded by `DEFAULT_SETSIZE`.

- **Bad**: `elemIds : \seq ELEMID` (unbounded enumeration)
- **Good**: `elemIds : \power ELEMID` (bounded by given set cardinality)

This loses ordering information. For invariant checking, ordering is rarely relevant — the key properties (membership, cardinality, subset relationships) are preserved with sets.

### Constraint 4: Bound All Inputs

Every input variable (`?` decorated) must have a finite range for ProB to enumerate. Implicit bounds from predicates are sometimes not enough.

- **Bad**: `bytesIn? > 0` with no upper bound
- **Good**: `bytesIn? > 0 \\ bytesIn? \leq maxBufSize`

### Constraint 5: Animation-Friendly Constants

Production constants (64, 1000, 16M) create enormous state spaces. Use small constants (3-4) in the spec for model checking. Document the production values in a comment.

### Constraint 6: No `Init*` Name Collisions

ProB searches for initialization schemas using a name heuristic. If any schema starts with `Init` (e.g., `InitFrameReaderState`), ProB may select it instead of the intended `Init` schema. Rename subsidiary init schemas (e.g., `ResetFrameReader`).

### Constraint 7: Frame All Variables in Every Operation

Every `\Delta State` operation must explicitly set **every** primed state variable. Unset variables cause "reading undefined variable" errors. This is verbose but necessary — ProB's B translation doesn't support Z's convention of leaving unmentioned variables unchanged via schema inclusion.

### Makefile Targets

```bash
make fuzz SPEC=docs/display-server.tex   # Type-check with fuzz
make prob SPEC=docs/display-server.tex   # Full ProB suite (init, animate, CBC, model check)
```

Default ProB parameters: `DEFAULT_SETSIZE=2`, `MAXINT=4`, `TIME_OUT=60000`. Override via make variables:

```bash
make prob SPEC=docs/foo.tex PROB_SETSIZE=3 PROB_MAXINT=8
```

---

## DES-010: PlotElement — ImPlot Title/ID Separation

**Date:** 2026-03-07
**Status:** ACCEPTED (known limitation)
**Topic:** How plot titles interact with ImGui's `##` ID separator

### Design

ImGui uses `##` as a delimiter to separate the visible label from the internal ID (e.g., `"My Plot##p1"` displays "My Plot" but uses "p1" as the ImGui ID). The `_render_plot` method appends `##{element_id}` to the title automatically — **unless** the title already contains `##`, in which case it assumes the caller embedded an explicit ID.

```python
plot_title = title if "##" in title else f"{title}##{eid}"
```

### Known Limitation

If a plot title legitimately contains `##` as display text (e.g., `"Issue ##42 Trend"`), the renderer will not append the element ID, causing ImGui to parse the fragment after `##` as the ID. This could produce incorrect IDs or visual glitches if two plots share the same post-`##` fragment.

### Why Accept This

- `##` in display text is extremely rare — it's an ImGui convention, not natural language.
- The alternative (always stripping and re-appending) adds complexity for a near-zero probability case.
- This matches the pattern used in the spike code (`spikes/d-json-vocabulary/renderer.py`).
- Users who need `##` in titles can work around it by pre-appending their own `##id` suffix.

### If This Causes Bugs

Replace the heuristic with unconditional append: strip any existing `##` suffix from the title, then always append `##{eid}`. This is a one-line change in `display.py:_render_plot`.

---

## DES-011: PlotElement — `plot_bars` API Compatibility

**Date:** 2026-03-07
**Status:** ACCEPTED
**Topic:** `implot.plot_bars` signature varies across imgui-bundle versions

### Design

The `_render_plot` method wraps `implot.plot_bars` in a `try/except TypeError` fallback:

```python
try:
    implot.plot_bars(s_label, x_data, y_data, 0.67)
except TypeError:
    implot.plot_bars(s_label, y_data, 0.67)
```

### Why

Across imgui-bundle versions, `plot_bars` has two signatures:

1. `plot_bars(label, x_values, y_values, bar_width)` — newer versions with explicit x positions
2. `plot_bars(label, values, bar_width)` — older versions with implicit x positions (0, 1, 2, ...)

The `try/except` handles both without requiring a minimum version pin. The fallback loses explicit x-positioning, which means bar charts will use sequential integer positions instead of the caller's x values on older versions.

### If This Causes Confusion

Pin a minimum imgui-bundle version in `pyproject.toml` and remove the fallback.

---

## DES-012: render_function Integration — Lifecycle, Hot Reload, and Event Routing

**Date:** 2026-03-07
**Status:** SETTLED
**Topic:** How the render_function element kind is wired into the display server

### Context

DES-004 established the two-layer rendering posture (declarative JSON + opt-in code). DES-005 listed `render_function` in the element vocabulary. This entry documents the implementation choices made when wiring the three building blocks — AST scanner (`ast_check`), consent dialog (`consent`), and code executor (`runtime`) — into the display server as a concrete element kind.

### Per-Element Lifecycle State

Each `render_function` element has a lifecycle: **pending consent → running / denied / errored**. The display server tracks this in a dict keyed by element ID:

```python
@dataclass
class _RenderFnState:
    source: str = ""
    dialog: ConsentDialog | None = None
    executor: CodeExecutor | None = None
    denied: bool = False
```

This is separate from `WidgetState` (which tracks interactive widget values like slider positions). `_RenderFnState` tracks a compile-and-run lifecycle, not a simple value.

### Renderer Phases

The `_render_render_function` method runs one of three phases per frame:

1. **Consent pending** — `state.dialog` is not None. Draws the consent modal. On Allow, creates or hot-reloads the executor. On Deny, sets `denied = True`. Returns early (nothing else renders while the modal is up).

2. **Denied** — Shows red text: `"[{id}] Code execution denied"`. Terminal state until the element is replaced or source changes.

3. **Running** — Calls `executor.render(dt, width, height)` each frame. If the executor has an error, shows the error message in red instead.

### Hot Reload vs Cold Reload

Two distinct paths were verified empirically:

**Cold reload** — `show()` (full scene replacement):
- `_handle_message` for `SceneMessage` calls `self._render_fn_state.clear()`
- Old executor is dropped, state dict is lost
- New consent required, fresh `CodeExecutor`, `ctx.state` starts empty
- Frame counter resets to 0

**Hot reload** — `update()` (patch source on existing element):
- `_apply_patch_set` changes the element's `source` field via `setattr`
- Next render frame detects `state.source != source`
- Old executor is stashed in the new `_RenderFnState`
- New consent dialog shown (security boundary — every source change requires re-consent)
- On Allow: `old_executor.hot_reload(source)` creates a new `CodeExecutor` with fresh compiled code but the **same `ctx.state` dict** and **same event callback**
- On Deny: old executor is discarded, element shows denied message

**Verified empirically:** Sent a render_function with a frame counter, clicked Allow, let it reach frame 1327. Patched the source via `update()` (added colored text, changed button label). After re-consent, frame counter continued at 1349 (gap is consent dialog time). State preserved.

### Event Routing

`ctx.send(action, data)` inside user code routes back to the agent through the existing event queue:

```
render(ctx) → ctx.send("clicked", {"frame": 452})
           → _event_callback(action, data)
           → _make_event_callback closure captures element_id
           → InteractionMessage(element_id="rf1", action="clicked", value={"frame": 452})
           → self._event_queue.append(...)
           → _flush_events() sends to all connected clients
           → agent calls recv() → "interaction:element=rf1,action=clicked,value=..."
```

The closure is created by a named method (`_make_event_callback`) rather than a lambda because mypy cannot infer the type of a lambda with default-argument capture (`_eid=eid`). The named method provides an explicit return type annotation.

Events from `render_function` elements are indistinguishable from events generated by declarative elements (button clicks, slider changes). The agent polls them uniformly with `recv()`.

### Source Change Detection

The renderer compares `state.source != source` each frame. If the source has changed (via `update` patch), it triggers the consent-then-hot-reload flow. This means:

- The agent can iteratively modify render functions while the display is live
- Every source change requires user consent (security invariant)
- State is preserved across source changes when using `update()` (hot reload)
- State is lost when using `show()` (cold reload / new scene)

### Deferred Imports

The consent, AST scanner, and runtime modules are imported inside `_render_render_function`, not at module level. This follows the existing display.py pattern where ImGui imports are deferred — allowing the module to be imported by unit tests that don't have a GPU context.

### Design Principle: Continuity of Data, Discontinuity of Trust

Each source change is a new trust decision (consent required), but application state persists so the user doesn't lose their work. This mirrors Smalltalk's live coding model where you can modify methods while objects retain their instance variables — except with a consent gate at each code change.
