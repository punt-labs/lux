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

```text
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

---

## DES-013: Window Chrome and Transparency Options

**Date**: 2026-03-07
**Status**: Implemented (borderless + top_most), documented (transparency)

### Context

The Lux display runs as an independent window alongside the terminal. Users want HUD-like behavior: a frameless overlay that floats above other windows. This requires understanding what HelloImGui's `AppWindowParams` exposes and what requires backend-level access.

### Available AppWindowParams

HelloImGui's `AppWindowParams` exposes these window chrome options:

| Param | Type | What it does |
|---|---|---|
| `borderless` | bool | Frameless window — no title bar, no OS chrome |
| `borderless_movable` | bool | Draggable from any point when borderless |
| `borderless_resizable` | bool | Resizable from edges when borderless |
| `borderless_closable` | bool | Show a close button in borderless frame |
| `borderless_highlight_color` | ImVec4 | Accent color for the borderless frame |
| `top_most` | bool | Always-on-top (all platforms) |
| `hidden` | bool | Start hidden (for tray-style apps) |
| `resizable` | bool | Standard resizable toggle |

### Transparency Analysis

Three levels of transparency exist, with decreasing feasibility:

1. **Window-level opacity** (whole window, uniform alpha): Achievable at runtime via `glfwSetWindowOpacity()` through the raw GLFW handle (`hello_imgui.get_glfw_window_address()`). Requires ctypes/cffi bridge.

2. **Transparent framebuffer** (see-through background, opaque content): Requires `GLFW_TRANSPARENT_FRAMEBUFFER` hint set *before* window creation. HelloImGui's Python bindings don't expose pre-creation window hints. Would need an upstream patch or a monkey-patched init sequence.

3. **Per-pixel alpha compositing**: Requires platform-specific compositing (macOS `NSWindow.alphaValue` + `NSWindow.isOpaque = false`). Beyond HelloImGui's abstraction layer.

### Decision

- **Borderless + top_most**: Implemented as toggleable menu items under Window menu. These use `hello_imgui.get_runner_params()` at runtime, which HelloImGui applies on the next frame.
- **Window-level opacity**: Deferred — requires GLFW handle bridge (bead lux-zlw.1).
- **Transparent framebuffer**: Deferred — requires upstream HelloImGui changes or pre-init hook.
- **Per-pixel transparency**: Out of scope — platform-specific, not portable.

### Runtime Toggle Behavior

Borderless and top_most are toggled via the Window menu. When borderless mode is active, the custom menu bar (Lux, Theme, Window) remains accessible because HelloImGui renders it inside the ImGui content area, not in the OS title bar. The `borderless_movable` flag ensures the window remains draggable.

Note: `remember_status_bar_settings` is set to `False` to prevent HelloImGui's ini file from overriding our programmatic settings (see status bar fix in this PR).

---

## DES-014: Command & Hook Architecture — CLI-First with Plugin Projection

**Date:** 2026-03-08
**Status:** ACCEPTED
**Topic:** How Lux exposes user commands, hooks, and slash commands following punt-kit standards

### Context

Lux has MCP tools (`show`, `update`, `clear`, `ping`, `recv`, `set_menu`, `set_theme`) that agents call to drive the display. But there is no user-facing command vocabulary — no way for a user to say "use Lux for visual output" the way `/vox on` tells the LLM to speak. This ADR defines the full command and hook architecture following [CLI standards](https://github.com/punt-labs/punt-kit/blob/main/standards/cli.md) and [plugin standards](https://github.com/punt-labs/punt-kit/blob/main/standards/plugins.md).

### Core Principle

**The CLI is the complete product.** Every capability is a CLI command first. MCP tools, slash commands, and hooks are projections of CLI functionality. A user who never opens Claude Code can use every feature.

### CLI Command Layers

#### Layer 1: Product Commands

| Command | What it does | MCP projection |
|---------|-------------|----------------|
| `lux notify y/n` | Toggle LLM encouragement to use visual output | `notify` MCP tool |
| `lux theme <name>` | Set the display theme | `set_theme` MCP tool (exists) |
| `lux status` | Current state: display running, theme, notify mode | `status` MCP tool |

#### Layer 2: Admin Commands

| Command | What it does |
|---------|-------------|
| `lux display` | Start the display server (exists) |
| `lux serve` | Start the MCP server (exists) |
| `lux version` | Print version (exists) |
| `lux doctor` | Check health: display server, socket, imgui-bundle |
| `lux install` | Register MCP server, create config directory |
| `lux enable` / `lux disable` | Toggle Lux in current project (creates/removes `.lux`) |

#### Layer 3: Hook Dispatchers (Internal)

| Command | What it does |
|---------|-------------|
| `lux hook stop` | Decision-block: generate visual summary before session ends |
| `lux hook post-bash` | Classify Bash output into visual signals |
| `lux hook session-start` | First-run setup (deploy commands, auto-allow tools) |

Shell scripts are thin gates. Business logic lives in `src/punt_lux/hooks.py` as testable pure functions.

### Slash Commands (Plugin Projection)

| Slash command | Calls | Maps to |
|--------------|-------|---------|
| `/lux on` | `notify` MCP tool with `mode: "y"` | `lux notify y` |
| `/lux off` | `notify` MCP tool with `mode: "n"` | `lux notify n` |
| `/lux` (no args) | `status` MCP tool | `lux status` |

Slash commands call MCP tools, not Bash → CLI. This follows the MCP-first command pattern from plugin standards.

### Call Path Selection

| Path | Latency | Used by |
|------|---------|---------|
| Hook → CLI | ~110ms | Stop hook, PostToolUse Bash, SessionStart |
| LLM → MCP tool | ~3.2s | Slash commands (`/lux on`, `/lux off`) |
| ~~LLM → Bash → CLI~~ | ~4.6s | **Avoided.** No slash command uses this path. |

### Why `y/n` Not `y/n/c`

Vox uses `y/n/c` (yes/no/chime-only) because audio has a meaningful middle state: the tool is active (listens for events, plays notification sounds) but doesn't speak full sentences. Lux has no equivalent middle state — the display is either something the LLM should actively use, or it's passive. A "chime" mode for visual output (flash the window? show a badge?) would be contrived. Two states are sufficient.

### Why `notify` Not `on`/`off`

The display server runs independently — `lux on` implies starting/stopping the display, which is wrong. The command toggles whether the LLM is *encouraged* to use the display, not whether the display exists. `notify` matches Vox's vocabulary (`vox notify y/n/c`) and makes the semantic clear: you're configuring notification behavior, not controlling a service.

---

## DES-015: Stop Hook — Decision-Block for Visual Summary

**Date:** 2026-03-08
**Status:** ACCEPTED
**Topic:** How the Stop hook forces a visual summary before session end

### Context

When a user's task completes and the LLM is about to stop, there's an opportunity to display a visual summary of what was accomplished — a dashboard, a diff view, a test results table. The Stop hook intercepts the stop event and tells the LLM to generate this visual output before ending.

This follows the same pattern as Vox's Stop hook, which forces a spoken recap before session end.

### Design

The Stop hook is a **decision-block**: it prevents the session from ending and instructs the LLM to take an action first.

```text
Session ending
  │
  ▼
Stop hook fires
  │
  ├── Config says notify: n → allow stop (exit 0, no output)
  │
  └── Config says notify: y
      │
      ├── No accumulated signals → allow stop
      │
      └── Has signals → BLOCK stop
          │
          Output: { "decision": "block",
                    "reason": "Display a visual summary before ending." }
          │
          LLM generates visual summary via show() / update()
          │
          LLM stops on next attempt (hook sees summary was shown)
```

### Call Path

```text
Claude Code Stop event
  → hooks/stop.sh (thin gate: check .lux/config.md)
  → lux hook stop (CLI dispatcher)
  → hooks.py:handle_stop() (pure function)
  → returns decision JSON
```

The shell script reads config to check if notify is enabled. If not, exits immediately (no Python startup cost). If enabled, delegates to `lux hook stop` which calls `hooks.py:handle_stop()`.

### Re-entry Guard

The hook must not block indefinitely. After the LLM generates one visual summary (detected by checking if a `show` or `update` tool was called since the last stop attempt), the hook allows the stop. This prevents infinite loops.

Implementation: the PostToolUse hook for Lux MCP tools sets a flag in config when `show` or `update` is called. The Stop hook checks and clears this flag.

### Why Block, Not Suggest

A non-blocking hook would add `additionalContext` suggesting the LLM show a summary. But the LLM is already stopping — it has decided its work is done. A suggestion in additional context is easily ignored. Blocking forces the LLM to act, which is the only way to guarantee the visual summary appears.

---

## DES-016: Signal Accumulation — PostToolUse Bash Classification

**Date:** 2026-03-08
**Status:** ACCEPTED
**Topic:** How Bash command output is classified into signals that inform the Stop hook

### Context

The Stop hook needs to know *what happened* during the session to generate a useful visual summary. A session that only edited files needs a diff view. A session that ran tests needs a results table. The PostToolUse Bash hook observes command output and classifies it into signals.

### Design

A PostToolUse hook registered on `Bash` tool calls classifies output into signal categories:

| Signal | Detected by | Visual summary |
|--------|------------|----------------|
| `test_results` | pytest/jest/cargo test output patterns | Test results table |
| `build_output` | make/cargo build/npm build patterns | Build status dashboard |
| `git_changes` | git diff/status/log output | Diff view or commit summary |
| `error_output` | Non-zero exit code, stderr patterns | Error details table |

Signals accumulate in `.lux/signals.json` (or equivalent state file) during the session. The Stop hook reads accumulated signals to decide what kind of visual summary to generate.

### Call Path

```text
Claude Code PostToolUse Bash event
  → hooks/post-bash.sh (thin gate: check .lux enabled)
  → lux hook post-bash (CLI dispatcher, reads stdin)
  → hooks.py:handle_post_bash(data) (pure classifier)
  → appends signal to state file
```

### Why Not Classify in the Stop Hook

The Stop hook fires once at session end. By that point, the Bash output is gone — it was consumed by earlier tool calls. The PostToolUse hook observes output as it happens, building up a picture of the session incrementally.

### Signal Storage

Signals are stored in `.lux/signals.json` as a simple array of `{type, timestamp, summary}` objects. The file is cleared at session start (by the SessionStart hook) and read at session end (by the Stop hook). This is session-scoped ephemeral state, not persistent configuration.

---

## DES-017: Config State — `.lux/config.md` with YAML Frontmatter

**Date:** 2026-03-08
**Status:** ACCEPTED
**Topic:** Where Lux stores per-project configuration

### Context

Lux needs to store per-project state: whether notify is enabled, the current theme, accumulated signals. This follows the same pattern as Vox's `.vox/config.md`.

### Design

```text
.lux/
  config.md          # YAML frontmatter + markdown (LLM-readable context)
  signals.json       # Session-scoped ephemeral state (cleared each session)
```

#### `config.md` format

```markdown
---
notify: "y"
theme: "imgui_colors_light"
---

# Lux Configuration

Visual output is enabled for this project. The LLM will use the Lux display
surface for dashboards, data views, and visual summaries.
```

The YAML frontmatter stores machine-readable config. The markdown body provides LLM-readable context that hooks inject as `additionalContext` during SessionStart.

### Why `.lux/` Not `.claude/lux.local.md`

The `.claude/` directory is for Claude Code's own state. Tool-specific config lives in its own dotdir (`.vox/`, `.biff/`, `.lux/`). This keeps tool state independent of Claude Code's lifecycle and makes it visible to non-Claude consumers (CLI users, scripts).

### Who Writes Config

| Writer | What | Path |
|--------|------|------|
| `lux notify y/n` (CLI) | Sets `notify` field | Direct YAML write |
| `notify` MCP tool | Sets `notify` field | Calls same function as CLI |
| `lux theme <name>` (CLI) | Sets `theme` field | Direct YAML write |
| `set_theme` MCP tool | Sets `theme` field | Calls same function as CLI |
| SessionStart hook | Creates config if missing, clears signals | Shell + CLI |

The model never touches config files directly — it uses the MCP or CLI layer. This is a hard rule from punt-kit CLI standards.

### Gitignore

`.lux/` should be gitignored. It contains user-specific state (notify preference, session signals) that should not be committed. Add to project `.gitignore`:

```gitignore
.lux/
```

---

## DES-018: Built-In Table Filtering — Client-Side Search, Sort, and Combo Filters

**Date:** 2026-03-08
**Status:** ACCEPTED
**Topic:** Whether filtering and search should be built into the table element or handled by the LLM via recv/update

### Context

The data explorer skill (DES-014 era) requires an interaction loop where the LLM receives filter events via `recv()`, recomputes filtered rows, and sends them back via `update()`. This works, but the LLM is doing mechanical work — case-insensitive substring matching, exact-match dropdown filtering — at ~6.4s round-trip latency (recv + update). The user experiences a multi-second delay for what should be instant keystroke response.

The question: should filtering be a **display server capability** (built into the table element) or an **LLM responsibility** (handled via the event loop)?

### Design

Add an optional `filters` field to `TableElement`. When present, the display server renders filter controls above the table and applies them at render time (60fps). No events are emitted for filter changes — the display handles it locally.

#### Protocol Addition

```python
@dataclass(frozen=True)
class TableFilter:
    """A filter control rendered above a table."""
    type: Literal["search", "combo"]
    column: int | list[int]       # column index(es) to filter on
    hint: str = ""                # placeholder text (search only)
    items: list[str] | None = None  # dropdown items (combo only, first item = "All")
```

```python
@dataclass(frozen=True)
class TableElement:
    # ... existing fields ...
    filters: list[TableFilter] | None = None  # NEW
```

#### JSON Wire Format

```json
{
  "kind": "table", "id": "pkg-table",
  "columns": ["Package", "Version", "Status", "License", "Downloads"],
  "rows": [
    ["punt-biff", "0.12.1", "Active", "MIT", "3,241"],
    ["punt-quarry", "0.10.1", "Active", "MIT", "2,887"],
    ["punt-lux", "0.0.1", "Beta", "MIT", "412"]
  ],
  "filters": [
    {"type": "search", "column": [0, 1], "hint": "Filter by name..."},
    {"type": "combo", "column": 2, "items": ["All", "Active", "Deprecated", "Beta"]},
    {"type": "combo", "column": 3, "items": ["All", "MIT", "Apache-2.0", "BSD-3"]}
  ],
  "flags": ["borders", "row_bg"]
}
```

#### Display Server Behavior

Each frame, the table renderer:

1. Reads current filter state (search text, combo selections) from ImGui widget state
2. Iterates full `rows`, applying all filters with AND logic
3. Renders only matching rows

Filter logic per type:

- **search**: case-insensitive substring match against the specified column(s). If `column` is a list, matches if *any* listed column contains the search text (OR within search, AND across filters).
- **combo**: exact match against `str(cell_value)`. First item in `items` is treated as "All" (no filter applied when selected).

A result count line (`"Showing N of M"`) is rendered automatically between the filters and the table body.

#### What Does NOT Move to the Display Server

| Capability | Why it stays with the LLM |
|-----------|--------------------------|
| Detail panel updates | Row selection → rich details requires understanding the data |
| Computed filters | Filters on derived values (e.g., "overdue" from a date field) need logic |
| Cross-table updates | Filtering one table affects another — requires orchestration |
| Data refresh | Re-reading the source (file, API, command) is an I/O operation |
| Custom filter logic | OR-within-category, range sliders, regex — future extensions |

These remain in the `recv()` → `update()` loop. The LLM handles intelligence; the display handles mechanics.

### The Three Layers

| Layer | Who | Latency | Examples |
|-------|-----|---------|---------|
| **Built-in safe** | Display server, declarative | 0ms (render-time) | Search, combo filter, sort by column |
| **LLM-driven** | recv() → update() loop | ~6.4s | Detail panel, computed fields, cross-table |
| **Code-on-demand** | render_function, consent gate | 0ms (render-time) | Custom visualizations, games |

Built-in filtering occupies the same trust level as the existing dispatch table — it's safe by construction because the display server only does predefined operations (substring match, exact match) on data the LLM already provided. No arbitrary code, no consent required.

### Impact on the Data Explorer Skill

The skill becomes simpler. Instead of teaching the LLM to build a filter → recv → update loop, it teaches the LLM to declare `filters` on the table element. The interaction section shrinks from "Phase 5: Interaction Loop" to "Phase 5: Detail Panel (Optional)" — only needed if the explorer includes a detail view.

The skill should document both paths: built-in filters for the common case, recv/update for custom behavior.

### Sort by Column (Future Extension)

A natural follow-on is built-in column sorting (click header to sort). This would be another declarative flag:

```json
{"kind": "table", "sortable": true, ...}
```

The display server handles sort state and re-orders rows at render time. Not in scope for the initial implementation but designed to fit the same pattern.

### Rejected: Linked Elements (Combo X Filters Table Y)

An alternative design would let any combo or input_text element declare a `filters_table` link to a table ID. This is more flexible (filters can live anywhere in the layout) but adds a new concept — cross-element references. The simpler design (filters are *part of* the table) avoids this complexity and covers the primary use case. If layout flexibility is needed, the LLM can always fall back to the recv/update path.

### Rejected: Client-Side Filter Scripts

Small JavaScript-like filter functions evaluated in the display (e.g., `row => row[4] > 1000`). This blurs the line with render_function and raises the same consent questions. The declarative filter types (search, combo) cover the common cases without running user-provided code.

## DES-019: Built-In Table Detail Panel — Row Selection with Split Layout

**Date:** 2026-03-08
**Status:** ACCEPTED
**Topic:** Whether row-selection → detail-panel should be built into the table element or handled by the LLM via recv/update

### Context

List/detail is one of the most common UI patterns: click an item in a list, see its details below. DES-018 moved filtering into the display server at 0ms latency. The same argument applies to detail panels — when the user clicks a row, the ~6.4s recv/update round trip to show pre-known detail data is unnecessary friction.

The LLM already knows the detail data at `show()` time. The question: can we send it all upfront and let the display server handle the selection → detail rendering locally?

### Design

Add an optional `detail` field to `TableElement`. When present, clicking a row renders a detail panel below the table. The display server handles selection state and detail rendering entirely — no events emitted, no round trips.

#### Protocol Addition

```python
@dataclass(frozen=True)
class TableDetail:
    """Detail data for each row, rendered when the row is selected."""
    fields: list[str]          # field names (e.g., ["ID", "Title", "Status", ...])
    rows: list[list[Any]]      # one row per table row, values for each field
    body: list[str]            # one body text per table row (long-form content)
```

```python
@dataclass(frozen=True)
class TableElement:
    # ... existing fields ...
    detail: TableDetail | None = None  # NEW
```

The `detail.rows` and `detail.body` lists are parallel to the table's `rows` — index 0 maps to table row 0, etc. This avoids key-based lookups and keeps the protocol simple.

#### JSON Wire Format

```json
{
  "kind": "table", "id": "issue-list",
  "columns": ["ID", "Title", "Status"],
  "rows": [
    ["ISS-001", "Fix login timeout", "Open"],
    ["ISS-002", "Add dark mode", "In Progress"]
  ],
  "detail": {
    "fields": ["ID", "Title", "Status", "Priority", "Assignee", "Created"],
    "rows": [
      ["ISS-001", "Fix login timeout", "Open", "P1", "alice", "2026-03-01"],
      ["ISS-002", "Add dark mode", "In Progress", "P2", "bob", "2026-03-02"]
    ],
    "body": [
      "The login flow times out after 30s on slow connections...",
      "Users have requested a dark theme for reduced eye strain..."
    ]
  },
  "flags": ["borders", "row_bg"]
}
```

#### Display Server Behavior

When `detail` is present:

1. **Selectable rows** — Table rows use `imgui.selectable()` with `span_all_columns` in column 0. Clicking a row stores its original index in widget state (`__tbl_sel_{table_id}`).
2. **Index tracking** — When filters are active (DES-018), visible row N maps to a different original row index. The renderer tracks `IndexedRow = tuple[int, list[Any]]` through filtering so detail lookup uses the correct original index.
3. **Detail panel** — Rendered in a scrollable `imgui.begin_child()` region that takes all remaining vertical space. Contains:
   - **Heading** — First field value (typically the title) rendered as bold separator text
   - **Field grid** — 2-column layout using a 4-column ImGui table (Field₁ | Value₁ | Field₂ | Value₂), fields paired two per row
   - **Body** — Full text content with word wrapping, separated from the field grid

The table list portion stays fixed; only the detail panel scrolls. This mimics standard list/detail UIs (email clients, file browsers, issue trackers).

#### Interaction with DES-018 Filters

Filters and detail compose naturally. When filters are active:

- Clicking a filtered row looks up the original index, not the visible position
- Changing filters auto-selects the first visible row so the detail panel always shows relevant content (prevents stale detail for a row that is no longer visible)
- The detail panel always shows data for the currently selected original row

#### What Does NOT Move to the Display Server

| Capability | Why it stays with the LLM |
|-----------|--------------------------|
| Data-source pagination | Loading next/previous pages requires knowing the data source (the display server handles scroll-based rendering of loaded rows natively via ImGui's table clipper) |
| Dynamic detail | Detail content that depends on external lookups (API calls, file reads) |
| Actions on selected row | "Close this issue", "Assign to me" — requires LLM orchestration |
| Multi-row selection | Bulk operations need LLM-driven logic |

These remain in the `recv()` → `update()` loop. Data-source pagination in particular was intentionally left to the LLM to keep the display server stateless about data sources. Scroll-based rendering of loaded rows is handled natively by ImGui's table clipper and requires no protocol support.

### Rejected: Separate Detail Element

An alternative would be a standalone `detail_panel` element type linked to a table by ID. This adds cross-element references (same issue as rejected in DES-018). Embedding detail data *in* the table element keeps it self-contained — one element, one dataset, one render path.

### Rejected: Key-Based Row Matching

Instead of parallel arrays, detail rows could use a key field to match table rows. This adds complexity (key extraction, lookup maps) for no practical benefit — the LLM constructs both arrays at the same time and can trivially keep them aligned.

---

## DES-020: SMP Font Coverage — Math Font Merge for Double-Struck Letters

**Date:** 2026-03-10
**Status:** ACCEPTED
**Topic:** How the display server renders Supplementary Multilingual Plane (SMP) characters

### Context

Characters above U+FFFF (the Basic Multilingual Plane) rendered as diamond replacement glyphs. Specifically, U+1D53D (Mathematical Double-Struck Capital F) used for Z notation's `\finset` was missing. The existing font stack (Arial Unicode + Apple Symbols on macOS, DejaVu Sans + Noto Sans Symbols2 on Linux) lacks coverage for the Mathematical Alphanumeric Symbols block (U+1D400-1D7FF).

### Design

Add a math font as a third merge font on each platform:

| Platform | Math font | Provides |
|----------|-----------|----------|
| macOS | `STIXTwoMath.otf` (ships with macOS) | U+1D400-1D7FF and other mathematical symbols |
| Linux | `NotoSansMath-Regular.ttf` | Same block via Noto family |

The font is merged via `hello_imgui.load_font()` with `merge_to_last_font = True`, same as the existing symbol fonts.

### Why No Glyph Range Specification

imgui 1.92+ introduced dynamic font loading: glyphs are rasterized on demand with no need to pre-specify codepoint ranges. Adding a font that contains the target glyphs is sufficient. Earlier imgui versions required explicit `ImFontGlyphRangesBuilder` configuration for non-Latin codepoints.

### Font Size and Rasterization

Double-struck characters have thin parallel strokes (two contours per letter). At the default 15px font size, the 1px gap between strokes can be anti-aliased into a single solid stroke, making them resemble regular letters. This is a bitmap rasterization limitation, not a glyph loading issue. Users can zoom via Lux > Increase Font (Cmd++) to see the detail.

BMP double-struck characters (U+2124 etc.) render from Arial Unicode (primary font) since merge fonts only fill gaps for codepoints not already present. SMP characters render from STIX/Noto Math (only source). The visual styles differ slightly between the two fonts.

### Rejected: Bundling a Font

Bundling a font file in the package would add weight and licensing complexity. Both STIX Two Math and Noto Sans Math ship with their respective OS distributions. If neither is present, the display degrades gracefully (replacement glyphs for those specific characters only).

## DES-021: Tools Menu — Multi-Client Registration and Routed Callbacks

### Problem

Multiple MCP servers (Lux, Vox, Biff, etc.) connect to the same Lux display server. Each wants to register menu items in a shared "Tools" menu. When the user clicks one, the display must route the callback only to the server that registered it.

Three architectural gaps block this:

1. **Last-writer-wins menus.** `MenuMessage` replaces `_agent_menus` wholesale (`display.py:1336`). A second caller's `set_menu` erases the first.
2. **Broadcast events.** `_flush_events()` sends every `InteractionMessage` to every connected client (`display.py:2614-2621`). No routing.
3. **No client identity.** `_accept_connections()` adds sockets to `_clients` with no identity handshake. The display cannot distinguish who sent what.

### Design Decisions

#### D1: Socket-FD-based identity (implicit), not explicit handshake

**Decision:** Use the socket file descriptor as the client identity key. No new handshake message.

**Rationale:** The display already tracks `_clients: list[socket.socket]` and `_readers: dict[int, FrameReader]` keyed by FD. Adding an explicit `IdentifyMessage` with a client name (e.g. "vox") would require:

- A new protocol message type
- Handling the "client hasn't identified yet" state
- Deciding what happens if two clients claim the same name

Socket FDs are unique, free, and require zero protocol changes. For the display's purposes — "who registered this menu item?" and "who should receive this click?" — the FD is sufficient. Client names are cosmetic and can be added later if menu items need human-readable "registered by" labels.

**Trade-off:** No human-readable client names in the Tools menu. Items are identified by their `id` field, not by which server registered them. This is acceptable because menu items already have `label` fields that describe what they do ("Refresh Beads", "Mute/Unmute"), and the registering server's identity is an implementation detail the user doesn't need.

#### D2: Additive menu registration via new `RegisterMenuMessage`, not extending `MenuMessage`

**Decision:** Introduce a new `RegisterMenuMessage` type. Keep `MenuMessage` unchanged for backward compatibility.

```python
@dataclass
class RegisterMenuMessage:
    """Register menu items owned by this client.

    Additive: each client's items are merged into the Tools menu.
    Replaces any previous registration from the same client (socket).
    Automatically cleaned up on disconnect.
    """
    items: list[dict[str, Any]]  # [{label, id, shortcut?, enabled?, icon?}]
    type: Literal["register_menu"] = "register_menu"
```

**Rationale:**

- `MenuMessage` replaces the entire menu list — this is correct behavior for a single client setting its own menus. Changing its semantics would break existing callers.
- `RegisterMenuMessage` is explicitly additive: each call replaces only *that client's* items, not the global list.
- The display merges all clients' registered items into a single "Tools" menu, sorted alphabetically by label.

**Wire format:** Same length-prefixed JSON as all other messages. `{"type": "register_menu", "items": [...]}`.

#### D3: Display-side routing for menu clicks, not client-side filtering

**Decision:** The display maintains a `_menu_owners: dict[str, int]` mapping (item ID → socket FD). When a menu item is clicked, the `InteractionMessage` is sent only to the owning socket. All other events (button clicks, slider changes, etc.) continue to broadcast.

**Rationale:**

- Client-side filtering would require every client to receive every event and discard irrelevant ones. This leaks information (Vox sees Biff's menu click IDs) and wastes bandwidth.
- Display-side routing is simple: look up the item ID in `_menu_owners`, send to that socket only. O(1) per click.
- Only menu items need routing. Scene elements (buttons, sliders) are always within a scene owned by the client that sent the `SceneMessage`. If we later need scene-element routing, we can extend the same pattern by tracking scene ownership.

**Trade-off:** Non-menu `InteractionMessage`s still broadcast. This is fine for now — scenes are typically owned by one client, and if multiple clients listen for the same button click, broadcasting is correct behavior (any interested party should hear it).

#### D4: Cleanup on disconnect

**Decision:** When `_remove_client(sock)` is called, remove all items in `_menu_owners` whose value matches `sock.fileno()`. The Tools menu updates automatically on the next frame.

This is the key invariant: **a client's menu items exist if and only if the client is connected.** No stale items, no manual unregister needed.

#### D5: `recv()` returns only routed events for menu items

**Decision:** `recv()` on the MCP side is unchanged — it reads the next message from the socket. Since the display only sends routed menu events to the owning client, `recv()` naturally returns only events the client cares about.

No client-side filtering needed. The routing is invisible to the `recv()` caller.

### Data Structures

```python
# DisplayServer additions:
_menu_registrations: dict[int, list[dict[str, Any]]]  # fd → items
_menu_owners: dict[str, int]                           # item_id → fd
_fd_to_client: dict[int, socket.socket]                # fd → socket (O(1) routing)
```

`_menu_registrations` stores each client's raw item list (for re-rendering the menu). `_menu_owners` is the reverse index (for routing clicks). `_fd_to_client` is a reverse index for O(1) socket lookup by FD, matching the existing `_readers: dict[int, FrameReader]` pattern. All three are maintained in `_accept_connections` and `_remove_client`.

### Menu Rendering

The existing `_show_agent_menu` renders per-menu dicts with `{label, items}`. The Tools menu replaces this with a single merged menu:

```python
def _show_tools_menu(self, imgui: Any) -> None:
    if not self._menu_registrations:
        return
    all_items = []
    for items in self._menu_registrations.values():
        all_items.extend(items)
    all_items.sort(key=lambda i: i.get("label", ""))
    if imgui.begin_menu("Tools"):
        try:
            for item in all_items:
                # ... same rendering as _show_agent_menu item loop
        finally:
            imgui.end_menu()
```

Existing `_agent_menus` and `set_menu`/`MenuMessage` continue to work for non-Tools menus (backward compatible).

### Event Routing Change

```python
def _flush_events(self) -> None:
    if not self._event_queue:
        return
    for event in self._event_queue:
        owner_fd = self._menu_owners.get(event.element_id)
        if owner_fd is not None:
            # Routed: send only to registering client (O(1) lookup)
            target = self._fd_to_client.get(owner_fd)
            if target is not None:
                self._send_to_client(target, event)
        else:
            # Broadcast: send to all (existing behavior)
            for client in list(self._clients):
                self._send_to_client(client, event)
    self._event_queue.clear()
```

### MCP Tool: `register_tool`

New MCP tool in `server.py`:

```python
@mcp.tool()
def register_tool(
    label: str,
    tool_id: str,
    shortcut: str | None = None,
    icon: str | None = None,
) -> str:
    """Register a menu item in the Lux Tools menu.

    The item appears in the shared Tools menu alongside items from other
    MCP servers. When the user clicks it, only this server receives the
    callback via recv().

    Items are automatically removed when the server disconnects.
    """
    client = _get_client()
    client.register_menu_item({
        "label": label,
        "id": tool_id,
        "shortcut": shortcut,
        "icon": icon,
    })
    return f"registered:{tool_id}"
```

The client library gets a corresponding `register_menu_item` method that accumulates items and sends a `RegisterMenuMessage`. `LuxClient` stores registered items in `self._registered_menu_items: list[dict[str, Any]]` and replays them during `connect()` if non-empty — making re-registration after display restart automatic regardless of which code path triggers reconnect.

### Item ID Uniqueness

Menu item IDs must be globally unique across all connected clients. If two servers both register `tool_id="refresh"`, the routing index (`_menu_owners`) silently maps that ID to whichever client registered last, while both items appear in the menu.

**Enforcement:** The display validates uniqueness at registration time. If an item ID is already claimed by a *different* client, the display logs a warning and rejects the registration. Same-client re-registration (replacing your own items) is allowed.

**Convention:** Namespace item IDs by project name: `lux_refresh_beads`, `vox_mute`, `biff_check_messages`. This avoids collisions without the display needing to auto-prefix.

### `scene_id` Policy for Menu Events

Menu click events are not associated with any scene. When lux-308 adds `scene_id` to `InteractionMessage`, menu events will have `scene_id=None`. Clients that consume both scene element events and menu events should check `scene_id` to distinguish them. This policy is defined now to prevent ambiguity after lux-308 ships.

### `ClearMessage` and Menu Registrations

`ClearMessage` clears scenes, events, and widget state. It does NOT clear `_menu_registrations` or `_menu_owners`. Menus are connection-scoped, not scene-scoped — they persist until the client disconnects or re-registers. This must be explicitly preserved in the `ClearMessage` handler implementation.

### Client Lookup: O(1) Reverse Index

The display maintains `_fd_to_client: dict[int, socket.socket]` alongside the existing `_readers: dict[int, FrameReader]`. Updated in `_accept_connections` and `_remove_client`. The routing lookup in `_flush_events` uses this index instead of scanning `_clients`:

```python
target = self._fd_to_client.get(owner_fd)
```

### Menu Position in Menu Bar

`_show_tools_menu` is called in `_show_menus` after `_show_window_menu` and before the `_agent_menus` loop. The Tools menu appears as the fourth menu: Lux | Theme | Window | Tools | (custom agent menus).

### Protocol Backward Compatibility

- Old clients that only use `MenuMessage` continue to work unchanged — `_agent_menus` is separate from `_menu_registrations`.
- **Old display servers do NOT gracefully handle unknown message types.** `message_from_dict` raises `ValueError` for unknown types (`protocol.py:1372`), and `_read_from_client` catches this and disconnects the client (`display.py:1290-1292`). Slice 1 must fix this: `message_from_dict` should return a passthrough sentinel for unknown types instead of raising, and `_handle_message` should silently skip unknown messages. This also partially addresses lux-rq4 (protocol debt).
- The `register_menu` type string doesn't collide with any existing type.

### Rejected Alternatives

**Extending MenuMessage with an `owner` field.** This would change the semantics of an existing message. Callers that don't set `owner` would break. A new message type is cleaner.

**Client-side event filtering.** Every client receives every event, checks if the element_id matches its registrations, discards the rest. This works but leaks inter-client information and makes `recv()` return irrelevant events that confuse the LLM caller.

**Explicit client identity handshake.** A new `IdentifyMessage` sent after connect. Adds protocol complexity with no concrete benefit — the socket FD already provides unique identity for routing purposes.

### Known Limitations

**Broadcast for non-menu events.** Scene element interactions (button clicks, slider changes) still broadcast to all clients. If Vox is connected while a kanban board is active, Vox receives card-click events it has no context for. The natural extension is scene-ownership routing (a `_scene_owners: dict[str, int]` mirror of `_menu_owners`), but this is deferred — it requires resolving scene ownership semantics (what happens when a scene is updated by a different client than the one that created it?).

**No human-readable client names.** Menu items don't show which server registered them. Items are identified by their `label` field ("Refresh Beads", "Mute/Unmute"), which describes the action. The registering server's identity is an implementation detail. If needed later, `RegisterMenuMessage` can be extended with an optional `source` field.

### Concrete Use Cases

| Server | Menu Item | On Click |
|--------|-----------|----------|
| Lux | Refresh Beads | Runs `lux show beads` via subprocess |
| Vox | Mute / Unmute | Toggles speech output |
| Biff | Check Messages | Runs `biff read` |

Each server calls `register_tool(label="Refresh Beads", tool_id="lux_refresh_beads")` on startup. The display merges all items into a single Tools menu. User clicks route to the registering server.

### Build Plan

Five iterative slices, each a working end-to-end increment:

| Slice | What | Demo |
|-------|------|------|
| 1 | **Additive menu registration** — `RegisterMenuMessage` type, display stores per-client items, merges into Tools menu, cleanup on disconnect. Also: fix `message_from_dict` to return passthrough for unknown types instead of raising (partial lux-rq4). | Two test clients register items → both appear in Tools menu → disconnect one → its items vanish |
| 2 | **Routed event delivery** — `_flush_events` routes menu clicks to owning client only | Click "Refresh Beads" → only Lux client receives the event, Vox client receives nothing |
| 3 | **Client library + MCP tool** — `LuxClient.register_menu_item()`, `register_tool` MCP tool, `recv()` gets routed events | MCP server calls `register_tool` → item appears → click → `recv()` returns the event |
| 4 | **First consumer: beads refresh** — Lux MCP server registers "Refresh Beads" on startup, handles the callback | Start Lux plugin → Tools > Refresh Beads → beads board refreshes |
| 5 | **Cross-server demo** — Vox registers "Mute/Unmute", both coexist | Lux + Vox connected → Tools shows both items → clicks route correctly |

Each slice is one PR. Slice N depends on slice N-1.

---

## DES-022: Workspace Model — Frames, World Menu, and Client Namespaces

### Problem

Lux currently renders all content in a single canvas area. Multiple connected clients (Lux plugin, Vox, Quarry, etc.) write scenes into a shared space. Collisions are managed via tabs — a pragmatic solution, but one that solves an *isolation* problem at the wrong layer. The tab mechanism conflates collision avoidance with content organization.

The Smalltalk/Pharo vision from CLAUDE.md calls for "a Pharo-like live environment where the MCP server is the message bus, Lux is the Morphic layer, and the agent can introspect and reshape the UI while it's running." This requires a proper windowing model: independent frames that clients can create, populate, and manage, within a shared workspace.

Three capabilities are missing:

1. **No frame isolation.** All scenes share one canvas. A beads board and an architecture diagram can't coexist as independent, movable views.
2. **No world menu.** There is no discovery surface for launching frames. The Tools menu (DES-021) routes callbacks, but doesn't provide a hierarchical, per-client namespace for "what can I do?"
3. **No client identity.** DES-021 established socket-FD-based identity for routing, but the display doesn't know a client's *name*. The World menu needs human-readable namespaces ("Lux", "Vox", "Quarry") — FDs aren't sufficient.

### Inspiration

Pharo/Squeak's environment provides the reference model:

- **Menubar** — persistent top-level menus (Pharo, Browse, Debug, Sources, System, Library, Windows, Help)
- **World menu** — a floating, nested, pinnable context menu opened anywhere in the workspace
- **Frames** — independent, movable, resizable windows with title bars (close/minimize/maximize). Some use internal tabs. Each is a standalone view.
- **Taskbar** — bottom bar showing minimized frames for quick switching

Lux adapts this model for an LLM-driven context: agents create frames via protocol, users interact via the World menu and frame chrome, and the display manages layout.

### Design Decisions

#### D1: Four-layer hierarchy — Workspace → Frames → Scenes → Elements

**Decision:** The display is a *workspace* containing *frames*. Each frame is an inner window with chrome (title bar, minimize, close, resize). Each frame contains one or more *scenes*, tabbed if multiple. Each scene contains *elements* (the existing element tree).

```text
Workspace (the Lux native window)
├── Menubar (environment chrome)
├── Frame: "Beads Explorer"          ← owned by lux plugin client
│   ├── Scene: "punt-labs/lux"       ← tab
│   ├── Scene: "punt-labs/vox"       ← tab
│   └── Scene: "punt-labs/quarry"    ← tab
├── Frame: "Architecture: Lux"       ← owned by lux plugin client
│   └── Scene: "lux-arch"           ← single scene, no tabs
├── Frame: "Quarry Search Results"   ← owned by quarry MCP client
│   └── Scene: "search-42"
└── Taskbar (minimized frames)
```

**Rationale:** This mirrors ImGui's native windowing model (`imgui.begin("title")` creates a window with chrome). Frames are the *isolation boundary* — each client's content lives in its own frame(s). Two clients cannot collide because they're in separate frames. Tabs within a frame become a content organization choice, not a collision avoidance mechanism.

**Trade-off:** More complex state management. The display must track frame lifecycle, z-order, positions, and which client owns which frame. This is a significant increase in display-side complexity.

#### D2: Frames are intrinsic to object types, always created by clients via protocol

**Decision:** Every `show()` targets a frame. The client specifies a `frame_id` in the `SceneMessage`. If the frame doesn't exist, the display creates it. If it does exist, the scene is added/updated within it. Frames are never created by the display autonomously.

**Rationale:** Frames are part of the object type's identity. A "Beads Explorer" is not just data — it's a frame with chrome, sizing behavior, and content layout. Whether the trigger is the client calling `show()` or the user clicking a World menu item, the *client* always provides the data and protocol. The menu click sends an event to the client, the client responds with a `SceneMessage` targeting a frame.

**Trade-off:** The display cannot pre-populate frames. Every frame requires a client to provide content. This is intentional — it keeps the display as a pure renderer with no business logic.

#### D3: Aggregation is content-driven, not automatic

**Decision:** Whether a frame uses tabs for multiple scenes is determined by the content type, not by collision avoidance. The client decides.

| View type | Aggregation | Rationale |
|-----------|-------------|-----------|
| Beads board | Tabbed (per project) | Cross-project comparison is valuable |
| Architecture diagram | Separate frames | Each diagram is its own context |
| Dashboard | Client's choice | Same system → tabs; different systems → separate frames |
| Data explorer | Separate frames | Each table is its own drill-down context |

**Rationale:** The previous tab-based collision avoidance was solving the wrong problem. With frame isolation, tabs become a deliberate UX choice. Beads aggregates because comparing backlogs across projects adds value. Architecture diagrams don't aggregate because each is a distinct visual context.

#### D4: World menu — per-client namespaces, automatic from handshake

**Decision:** The World menu is a hierarchical menu where each connected client gets its own submenu, named automatically from the client's identity declared during the connection handshake. Clients register items within their namespace. Lux adds a few environment-owned items.

```text
World
├── Lux                    ← lux plugin's namespace (from handshake)
│   ├── Beads Explorer
│   └── Architecture Diagram
├── Vox                    ← vox plugin's namespace
│   └── Audio Monitor
├── Quarry                 ← quarry's namespace
│   └── Search...
└── ─────────────
    ├── Minimize All       ← Lux-owned environment items
    └── Close All
```

**Rationale:** Automatic namespacing from the handshake eliminates a registration step. Each client declares its display name once on connect, and all its World menu items appear under that name. This is consistent with how Pharo organizes its menus by package/tool. The handshake already exists (ReadyMessage response) — extending it with a client name is minimal protocol cost.

**Implication for DES-021 D1:** The socket-FD-based identity decision remains valid for *routing*. But the World menu needs human-readable names for *display*. This means the client must declare a display name during connect. This is a protocol extension: an optional `name` field in the connect handshake (or a new `IdentifyMessage` sent after ReadyMessage). The FD remains the routing key; the name is cosmetic.

#### D5: Handshake-based client identity replaces FD-only identity

**Decision:** Extend the connection protocol so clients declare a display name. The recommended approach: add a `ConnectMessage` sent by the client after receiving `ReadyMessage`, containing `name: str` (e.g. "Lux", "Vox", "Quarry"). The FD remains the internal routing key. The name is used for World menu namespacing and future UI labeling (e.g. "Frame owned by Vox").

**Rationale:** FD-based identity (DES-021 D1) was correct for its scope — routing menu clicks doesn't need human-readable names. But the World menu and frame ownership display require names. Adding a `ConnectMessage` is a single protocol addition that solves both. Clients that don't send a `ConnectMessage` get a fallback name like "Client 3" (from their FD).

**Trade-off:** Adds one new message type to the protocol. The display must handle the "client hasn't identified yet" state — but this is simple: use the fallback name until `ConnectMessage` arrives. No blocking; the handshake is optimistic.

### Frame Lifecycle

| Event | Protocol Message | Direction |
|-------|-----------------|-----------|
| Create/update frame | `SceneMessage` with `frame_id` | Client → Display |
| Close frame (user) | `InteractionMessage` with `action: "frame_close"` | Display → Client |
| Minimize frame (user) | `InteractionMessage` with `action: "frame_minimize"` | Display → Client |
| Client disconnect | (implicit) | Display removes client's frames |

The display sends frame lifecycle events (close, minimize) to the owning client. The client can react — e.g., a Beads Explorer might save state before closing, or ignore the close and keep the frame open (like a dirty-document dialog).

### World Menu Lifecycle

| Event | Protocol Message | Direction |
|-------|-----------------|-----------|
| Register items | `RegisterMenuMessage` with `menu: "World"` and `path` | Client → Display |
| User clicks item | `InteractionMessage` with `action: "menu"`, `value: {menu: "World", ...}` | Display → Client |
| Client disconnect | (implicit) | Display removes client's World menu items |

The existing `RegisterMenuMessage` (DES-021) is extended with optional fields: `menu` (defaults to `"Tools"` for backward compatibility) and `path` (list of strings for nesting, e.g. `["Beads Explorer"]`). Items registered with `menu: "World"` appear under the client's automatic namespace.

### SceneMessage Extension

The `SceneMessage` gains an optional `frame_id: str` field:

- **Present:** Scene targets the named frame. Frame is created if it doesn't exist.
- **Absent (backward compat):** Scene renders in a default frame (preserving current behavior for clients that don't know about frames).

Additional optional frame metadata on `SceneMessage`:

- `frame_title: str` — title bar text (defaults to `scene_id`)
- `frame_size: tuple[int, int]` — initial size hint (width, height)
- `frame_flags: dict` — ImGui window flags (no_resize, no_collapse, etc.)

### Spike Recommendation

This is a fundamental architectural change to the display server. Before committing to the full build plan, a **spike** should prove out the core mechanism:

**Spike scope:** Modify the display server to render scenes inside `imgui.begin()`/`imgui.end()` windows (frames) instead of the current single-canvas approach. Demonstrate:

1. Two frames coexisting, independently movable and resizable
2. Frame chrome (title bar, close button) functioning
3. Scenes rendering correctly inside frames (existing element dispatch)
4. Frame close generating an interaction event back to the client

**Spike non-goals:** World menu, taskbar, handshake identity, RegisterMenuMessage extensions. These build on top of frames and can be added incrementally once the core frame mechanism works.

**Risk the spike validates:** ImGui's `begin()/end()` windowing works with the existing scene renderer dispatch table. The display's render loop can manage multiple concurrent frames without state leakage between them. Performance remains acceptable at 60fps with multiple open frames.

### Build Plan (Post-Spike)

| Slice | What |
|-------|------|
| 1 | **Spike: frame rendering** — SceneMessage `frame_id`, display creates inner windows, scene renders inside frame, close button sends event |
| 2 | **ConnectMessage + client identity** — clients declare name on connect, display tracks names, fallback for unnamed clients |
| 3 | **World menu registration** — extend RegisterMenuMessage with `menu`/`path` fields, display renders nested World menu with per-client namespaces |
| 4 | **Taskbar** — bottom bar showing minimized frames, click to restore |
| 5 | **Frame aggregation** — multiple scenes in one frame as tabs, client-controlled |
| 6 | **First consumer migration** — migrate beads board from current canvas to framed model |

Each slice is one PR. Slice 1 is the spike — if it reveals blocking issues, the plan adapts before investing in slices 2-6.

### Rejected Alternatives

**Tabs as the isolation model (current approach).** Works for collision avoidance but conflates two concerns: isolation and content organization. Tabs should be a content choice, not a safety mechanism.

**OS-level windows for each frame.** ImGui supports native OS windows, but this breaks the "single Lux window" model and makes the workspace feel like separate applications rather than an integrated environment.

**Server-side frame creation.** The display could create frames when clients connect. But this introduces business logic into the renderer — the display shouldn't know what a "Beads Explorer" is. Frames are the client's domain.

**Flat World menu (command palette style).** A searchable flat list would be simpler but loses the per-client namespace organization that makes the menu navigable when many servers are connected. The nested model mirrors Pharo's organization and scales better.

### Known Limitations

**No drag-and-drop between frames.** Pharo's Morphic supports dragging objects between windows. Lux frames are isolated — content can't move between them without client coordination.

**No persistent layout.** Frame positions and sizes reset on display restart. Layout persistence (save/restore frame arrangement) is deferred — it requires a layout state file and is orthogonal to the core frame mechanism.

**No frame-to-frame communication.** Frames owned by different clients can't directly interact. The agents (LLM callers) can coordinate via MCP tools, but there's no display-level inter-frame messaging.

---

## DES-023: Dependency Layering — Lightweight Install via Extras

**Date:** 2026-03-12
**Status:** ACCEPTED
**PR:** #54

### Problem

`pip install punt-lux` pulls ~66 MB of transitive dependencies:

| Package | Size |
|---------|------|
| imgui-bundle | 27 MB |
| numpy | 18.7 MB |
| Pillow | 12.5 MB |
| PyOpenGL | 7.5 MB |

Consumers like Vox and Z-Spec only need `LuxClient` + protocol types — ~15 KB of pure Python with zero heavy deps. Forcing them to pay 66 MB for a client socket library is unreasonable.

### Design

Split dependencies using Python optional extras. Heavy display deps move from base `dependencies` to `[project.optional-dependencies] display`. The base install includes only lightweight packages (typer, rich, fastmcp, pydantic — ~2 MB).

```toml
dependencies = [
    "typer>=0.15.0,<1",
    "rich>=13.0.0,<14",
    "fastmcp>=3.0.0,<4",
    "pydantic>=2.0.0,<3",
]

[project.optional-dependencies]
display = [
    "imgui-bundle>=1.6.0",
    "Pillow>=11.0.0",
    "numpy>=2.0.0",
    "PyOpenGL>=3.1.0",
    "setproctitle>=1.3.0",
    "pyobjc-framework-Cocoa>=10.0; sys_platform == 'darwin'",
]
```

#### Why this works without refactoring

The split is surgical because the existing code already practiced lazy imports:

1. **`protocol.py`** — pure stdlib (json, socket, struct, dataclasses)
2. **`paths.py`** — pure stdlib (os, subprocess, pathlib)
3. **`client.py`** — imports only from protocol.py and paths.py
4. **`display.py`** — imports numpy and PIL at module level, imgui_bundle in method bodies
5. **`__main__.py`** — imports display.py lazily inside CLI command functions

The dependency arrow points one way: display → client → protocol. Client code never imports from display. This meant zero import restructuring — just move the deps and add guards.

#### Guard pattern

`lux display` catches `ModuleNotFoundError`, checks `exc.name` against known display modules, and prints a helpful install hint. Unrelated `ModuleNotFoundError` is re-raised to avoid masking real bugs:

```python
try:
    from punt_lux.display import DisplayServer
except ModuleNotFoundError as exc:
    _display_modules = {"imgui_bundle", "numpy", "PIL", "OpenGL"}
    if exc.name and exc.name.split(".")[0] in _display_modules:
        typer.echo("Display extras not installed. Run: pip install 'punt-lux[display]'", err=True)
        raise typer.Exit(code=1) from None
    raise
```

#### Public API cleanup

`CodeExecutor` and `RenderContext` were removed from `punt_lux.__init__` exports. They're display-internal (only used by `display.py`) and remain importable from `punt_lux.runtime` directly. No external consumers exist.

#### CI impact

CI workflows changed from `uv sync --frozen --extra dev` to `uv sync --frozen --extra dev --extra display`. The full test suite exercises display code, so CI must install all extras even though library consumers don't need them.

### Alternatives Considered

**Separate repo (`punt-lux-client`).** Cleanest package name signal, but requires cross-repo coordination for protocol changes. Every protocol addition would need a release of `lux-client` before `lux` could use it. Rejected for coordination overhead.

**Namespace subpackage in same repo.** `punt-lux-client` as a separate build target from the same source tree. Would require a monorepo build tool (e.g., uv workspaces). Rejected as over-engineered for the current scope.

**Extras split (chosen).** One repo, one release cycle. Consumers `uv add punt-lux` and get the lightweight client. End users `pip install 'punt-lux[display]'` for the full stack. The package name doesn't signal "lightweight" but the README and `lux doctor` do.

### Outcome

Base install dropped from ~66 MB to ~2 MB. Vox and Z-Spec benefit automatically — both already gate punt-lux behind an optional `lux` extra in their own pyproject.toml. Pattern codified in punt-kit standards: [python.md § Dependency layering](https://github.com/punt-labs/punt-kit/blob/main/standards/python.md) and [distribution.md § EXTRAS pin](https://github.com/punt-labs/punt-kit/blob/main/standards/distribution.md).

---

## DES-024: Table Row Select Event

**Date:** 2026-03-12
**Status:** ACCEPTED
**PR:** #53

### Problem

DES-019 established that row selection with a detail panel runs entirely client-side — no events, no round trips. But some use cases need the agent to *know* when the user selects a row: opening a detail view in a different frame, navigating to a file, or triggering a follow-up action. The detail panel handles the common case (show pre-known data); row_select handles the agentic case (agent reacts to selection).

### Design

When a table has `copy_id` set (the flag that makes rows selectable for copy), clicking a row emits an `InteractionMessage` with `action="row_select"`. The message includes the row index and row data so the agent can act on it without re-querying.

```python
InteractionMessage(
    element_id="issue-table",
    action="row_select",
    value={"index": 3, "data": ["ISS-004", "Refactor auth", "Open"]},
)
```

The agent reads this via `recv()` and can respond however it wants — update another frame, open a file, call an API.

#### Relationship to DES-019

DES-019's detail panel and DES-024's row_select are independent. A table can have:

- Detail panel only (common case — show data, no agent involvement)
- Row select only (agent-driven — click triggers agent action)
- Both (detail panel shows data, agent also gets notified)
- Neither (static display table)

The `copy_id` flag gates selectability. Tables without it remain non-interactive.

---

## DES-025: Frame Auto-Focus

**Date:** 2026-03-12
**Status:** ACCEPTED
**PR:** #53

### Problem

When an agent sends a scene update to a frame that is behind other frames or minimized, the user doesn't notice the update. The frame silently updates in the background. This violates the principle of least surprise — if an agent is actively populating a frame, the user should see it.

### Design

When a frame receives a scene update via `_handle_framed_scene`, the display server sets `imgui.set_next_window_focus()` on that frame's next render pass. If the frame is minimized (collapsed), it is also restored. This brings the frame to the front of the z-order.

The focus is set via ImGui's `set_next_window_focus()` which applies once on the next frame, then reverts to normal z-ordering. The user can immediately switch to another frame — auto-focus doesn't "trap" focus.

### Trade-off

This means a background agent continuously updating a frame will keep stealing focus. In practice this hasn't been a problem because agent updates are infrequent (one `show()` call per task, not a continuous stream). If continuous updates become common (e.g., live dashboards), a `no_auto_focus` frame flag could be added to DES-022's `frame_flags` vocabulary.

---

## DES-026: Markdown Font Size — Match imgui_md to ImGui Default

**Date:** 2026-03-14
**Status:** ACCEPTED
**Bead:** lux-sc1

### Problem

`MarkdownElement` renders body text noticeably larger than `TextElement` and other ImGui-rendered text. This creates a jarring visual hierarchy where markdown annotations dominate the UI. Observed in z-spec's tutorial browser, where lesson annotations overflowed the paged group frame. The z-spec team had to fall back to plain text elements.

Two sub-issues:

1. Markdown body text larger than ImGui default text
2. Markdown text doesn't wrap at parent container boundaries

### Root Cause

imgui_md (the markdown renderer bundled with imgui-bundle) loads **its own Roboto fonts** from bundled assets, completely independent of the system fonts Lux loads via `hello_imgui.load_font()`. Even at the same nominal pixel size, Roboto has different visual metrics (larger x-height, taller ascenders) than system fonts like Arial Unicode or SF Pro, making it appear visually larger.

The `MarkdownFontOptions.regular_size` field (default 16.0) controls the **display size**, not the rasterization size. Since v1.92, imgui-bundle always rasterizes fonts at 16px but can display them at any size via `ImGui::PushFont(font, size)`.

### Key Constraint: `InitializeMarkdown` Static Guard

`imgui_md::InitializeMarkdown` has a C++ `static bool wasCalledAlready` guard. It silently drops the second call. This means:

- Setting both `with_markdown = True` AND `with_markdown_options = <custom>` does **not** work — the runner may call `InitializeMarkdown` twice, and the custom options are dropped.
- Calling `imgui_md.initialize_markdown()` in `_on_post_init` does nothing — it's already been called during `immapp.run()` setup.

### Solution

Set `addons.with_markdown_options` with `regular_size = 13.0` and do **not** also set `with_markdown = True`:

```python
md_opts = imgui_md.MarkdownOptions()
md_opts.font_options.regular_size = 13.0
addons.with_markdown_options = md_opts
# Do NOT set addons.with_markdown = True
```

The runner code checks `withMarkdown || withMarkdownOptions.has_value()`, so setting options alone enables markdown. The 13px display size for Roboto visually matches the system font at 16px after `font_scale_main` (1.1x) is applied.

The primary font was also bumped from 15px to 16px for better readability at the default scale. This is independent of the markdown fix — the size mismatch existed at both 15px and 16px because the root cause is different typefaces (system font vs Roboto), not different sizes.

For wrapping: `imgui.push_text_wrap_pos(0.0)` before `render_unindented()` constrains text to the window's work rect boundary, which respects frame/group padding.

### Rejected Approaches

**Changing the primary font to 16px to "match" imgui_md.** Doesn't help — Roboto and system fonts have different metrics at the same nominal size. The visual mismatch persists.

**`imgui.set_window_font_scale()`.** Does not exist in the v1.92 Python bindings.

**Temporarily modifying `font_scale_main` during markdown render.** Would work in theory but is fragile — the scale change could affect nested elements, and the ratio depends on knowing both font sizes at render time.

**Calling `initialize_markdown()` in `_on_post_init`.** Silently dropped by the static guard — the function was already called during `immapp.run()` setup.

---

## DES-027: Application Containment — the `apps/` Subsystem

**Date:** 2026-03-14
**Status:** ACCEPTED

### Problem

Lux ships with a Beads Browser application that lets users view their project's issue board in a Lux frame. But the beads issue tracker is a separate product (`punt-beads`) maintained by a different team. Embedding beads-specific business logic — JSONL parsing, issue filtering and sorting, table layout — inside Lux's display server or MCP server couples Lux to a product it doesn't own. If beads changes its data format, Lux breaks. If another team wants to build a Lux applet (e.g., a Quarry search viewer), there's no pattern to follow.

### Design Principle

**Lux is a renderer. Applications are guests.**

DES-022 D2 established that "the display shouldn't know what a Beads Explorer is — frames are the client's domain." This principle extends beyond the display server to the entire Lux codebase. Application-specific business logic lives in `src/punt_lux/apps/`, a containment boundary that isolates guest code from Lux internals.

### Containment Rules

1. **`apps/` modules import only `LuxClient` and `protocol` types.** No imports from `display.py`, `hooks.py`, `server.py`, or other Lux internals. The dependency rule: host modules (`server.py`, `hooks.py`, `show.py`) import from `apps/`; `apps/` modules import only from `client` and `protocol` — never from host modules.

2. **Pure data functions are testable without a display.** `load_beads()` and `build_beads_payload()` are pure functions that read files and return dicts. They can be tested, extracted, or replaced without touching the renderer.

3. **Wiring lives in the host, not the app.** The MCP server (`server.py`) registers the menu item and callback. The hook dispatcher (`hooks.py`) triggers refreshes. The CLI (`show.py`) exposes the command. The app module itself has no knowledge of menus, hooks, or CLI — it just builds content and sends it to a `LuxClient`.

4. **Each app is extractable.** `apps/beads.py` is designed to move to the `punt-beads` repo as an optional Lux integration. When that happens, Lux removes `apps/beads.py` and the wiring in `server.py`/`hooks.py`/`show.py`. The beads team owns their applet; Lux provides the rendering surface.

### Current Structure

```text
src/punt_lux/
├── apps/
│   ├── __init__.py
│   └── beads.py          ← guest: data loading + table layout
├── server.py             ← host: menu registration + callback wiring
├── hooks.py              ← host: PostToolUse Bash → auto-refresh
├── show.py               ← host: CLI `lux show beads`
└── display.py            ← renderer: knows nothing about beads
```

**Surface area per app:**

| Layer | What the host provides | What the app provides |
|-------|----------------------|---------------------|
| Menu | `declare_menu_item` + `on_event` callback in `server.py` | Click handler calls `render_*()` |
| Hook | PostToolUse matcher in `hooks.json` + dispatcher in `hooks.py` | Nothing — refresh is the host's concern |
| CLI | `show_app.command()` in `show.py` | `load_*()` + `build_*_payload()` |
| Display | Frame rendering (DES-022) | Nothing — the display is generic |

### Future: `lux-applets` Extraction

When multiple apps exist (beads, quarry, z-spec tutorial, etc.), the `apps/` directory becomes its own package — `punt-lux-applets` or similar — that depends on `punt-lux[client]` (the lightweight install from DES-023). Each applet is a module with the same contract:

- `load_*()` — pure data loading
- `build_*_payload()` — pure layout construction
- `render_*_board(client)` — send to display

The MCP server discovers and wires applets at import time. Applets that fail to import (missing dependencies) are silently skipped — the menu item simply doesn't appear.

### Why Not a Plugin System Now

A formal plugin/applet registry with entry points, discovery, and lifecycle management is premature. There is exactly one app (beads), and it may move to its own repo soon. The `apps/` directory with manual wiring is the minimum viable containment. If a third app arrives, the pattern will be clear enough to extract into a registry.

### Relationship to DES-022

DES-022's rejected alternative — "Server-side frame creation: the display could create frames when clients connect, but this introduces business logic into the renderer" — is the same principle applied at the codebase level. The display server is a pure renderer. The MCP server is a protocol bridge. Business logic lives in `apps/`, and the wiring that connects apps to menus, hooks, and CLI lives in the host modules. No layer reaches into another's domain.
