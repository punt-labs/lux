# Lux Design Decision Log

> **Status:** historical decision log and rationale record. It is not the
> canonical architecture source. For architecture intent, start with
> `docs/architecture/target/target.md` for the rewrite target,
> `docs/architecture/system.tex` for the prior/current system view, and
> `docs/standards/python-oo.md` for implementation rules. Some entries below
> reference documents that have been removed from the working tree; use git
> history if you need them.

This file records design decisions, prior approaches, and their outcomes. Use
it as background and rationale, not as the primary architecture guide.

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
**Status:** SETTLED (partially superseded)
**Topic:** How much control Claude has over the display surface

> **Partially superseded (v0.19.0):** The full-JSON-vocabulary decision stands
> and is the shipped product. The "opt-in code running" posture (agent-supplied
> Python via `render_function`) was superseded by Hub-side handler dispatch
> (the io-model — DES-035/DES-036). See DES-012.

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
**Status:** SETTLED
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
**Status:** REJECTED (never implemented)
**Topic:** Which image generation provider to use initially

### Design

OpenAI image generation (DALL-E 3 or gpt-image-1) as the first backend.

### Outcome

Never implemented. Lux focused on data display (tables, dashboards, diagrams) rather than image generation. The ImageElement renders images from file paths or base64 data, but there is no generation backend. This ADR is closed as rejected — image generation is out of scope for Lux v1.

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
**Status:** SUPERSEDED (v0.19.0)
**Topic:** How the render_function element kind is wired into the display server

> **Superseded (v0.19.0):** `render_function` is not a registered element kind.
> Interaction is Hub-side handler dispatch (the io-model — see DES-035/DES-036),
> not agent-supplied Python executed in the display. Code-execution scaffolding
> survives only in `src/punt_lux/runtime.py`; it is not the v0.19.0 interaction
> path.

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
**Status:** SUPERSEDED (v0.19.0)
**Topic:** How Bash command output is classified into signals that inform the Stop hook

> **Superseded (v0.19.0):** The `signals.json` signal-accumulation mechanism is
> not present in the shipped code; `ConfigManager` allows only the `display`
> key. This ADR's subsystem no longer exists. Retained for history.

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
**Status:** SUPERSEDED (v0.19.0)
**Topic:** Where Lux stores per-project configuration

> **Superseded (v0.19.0):** Shipped config is `.punt-labs/lux.md` with a single
> `display` key — not `.lux/config.md` with a `notify` key. It is read/written
> via the `display_mode` / `set_display_mode` MCP tools, which now require an
> absolute `repo` argument (lux-r929); `luxd` holds no display-config state.
> There is no `lux notify` CLI or `signals.json`. See `src/punt_lux/config.py`.

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

New MCP tool in `tools.py`:

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

The client library gets a corresponding `register_menu_item` method that accumulates items and sends a `RegisterMenuMessage`. `DisplayClient` stores registered items in `self._registered_menu_items: list[dict[str, Any]]` and replays them during `connect()` if non-empty — making re-registration after display restart automatic regardless of which code path triggers reconnect.

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
| 3 | **Client library + MCP tool** — `DisplayClient.register_menu_item()`, `register_tool` MCP tool, `recv()` gets routed events | MCP server calls `register_tool` → item appears → click → `recv()` returns the event |
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

Consumers like Vox and Z-Spec only need `DisplayClient` + protocol types — ~15 KB of pure Python with zero heavy deps. Forcing them to pay 66 MB for a client socket library is unreasonable.

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
3. **`display_client.py`** — imports only from protocol.py and paths.py
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

> **Follow-on (2026-05-17):** `dev` was subsequently relocated from `[project.optional-dependencies]` to `[dependency-groups]` (PEP 735) — `dev` was never a real PyPI extra and shouldn't have been exposed as one. uv installs default dependency-groups automatically on `uv run`/`uv sync`, so the canonical CI invocation is now `uv sync --locked --extra display`. The display extra remains a `[project.optional-dependencies]` entry because it *is* a real consumer-facing extra (`pip install 'punt-lux[display]'`). `--locked` replaced `--frozen` to assert lockfile/manifest consistency rather than merely skip lockfile updates.

### Alternatives Considered

**Separate repo (`punt-lux-client`).** Cleanest package name signal, but requires cross-repo coordination for protocol changes. Every protocol addition would need a release of `lux-client` before `lux` could use it. Rejected for coordination overhead.

**Namespace subpackage in same repo.** `punt-lux-client` as a separate build target from the same source tree. Would require a monorepo build tool (e.g., uv workspaces). Rejected as over-engineered for the current scope.

**Extras split (chosen).** One repo, one release cycle. Consumers `uv add punt-lux` and get the lightweight client. End users `pip install 'punt-lux[display]'` for the full stack. The package name doesn't signal "lightweight" but the README and `lux doctor` do.

### Outcome

Base install dropped from ~66 MB to ~2 MB. Vox and Z-Spec benefit automatically — both already gate punt-lux behind an optional `lux` extra in their own pyproject.toml. Pattern codified in punt-kit standards: [python.md § Dependency layering](https://github.com/punt-labs/punt-kit/blob/main/standards/python.md) and [distribution.md § EXTRAS pin](https://github.com/punt-labs/punt-kit/blob/main/standards/distribution.md).

> **Follow-on (2026-05-21):** `pyobjc-framework-Cocoa` removed from the
> `[display]` extra. It was added exclusively for the macOS Dock-hiding
> call (`NSApplication.setActivationPolicy_(NSApplicationActivationPolicyAccessory)`),
> which has been reversed — the display server now runs as a normal Dock
> app per GLFW's default activation policy. `pyobjc-framework-Quartz`
> remains, pre-staged for DES-028 (CG screenshot approach).

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

1. **`apps/` modules import only `DisplayClient` and `protocol` types.** No imports from `display.py`, `hooks.py`, `tools.py`, or other Lux internals. The dependency rule: host modules (`tools.py`, `hooks.py`, `show.py`) import from `apps/`; `apps/` modules import only from `display_client` and `protocol` — never from host modules.

2. **Pure data functions are testable without a display.** `load_beads()` and `build_beads_payload()` are pure functions that read files and return dicts. They can be tested, extracted, or replaced without touching the renderer.

3. **Wiring lives in the host, not the app.** The MCP server (`tools.py`) registers the menu item and callback. The hook dispatcher (`hooks.py`) triggers refreshes. The CLI (`show.py`) exposes the command. The app module itself has no knowledge of menus, hooks, or CLI — it just builds content and sends it to a `DisplayClient`.

4. **Each app is extractable.** `apps/beads.py` is designed to move to the `punt-beads` repo as an optional Lux integration. When that happens, Lux removes `apps/beads.py` and the wiring in `tools.py`/`hooks.py`/`show.py`. The beads team owns their applet; Lux provides the rendering surface.

### Current Structure

```text
src/punt_lux/
├── apps/
│   ├── __init__.py
│   └── beads.py          ← guest: data loading + table layout
├── tools.py              ← host: menu registration + callback wiring
├── hooks.py              ← host: PostToolUse Bash → auto-refresh
├── show.py               ← host: CLI `lux show beads`
└── display.py            ← renderer: knows nothing about beads
```

**Surface area per app:**

| Layer | What the host provides | What the app provides |
|-------|----------------------|---------------------|
| Menu | `declare_menu_item` + `on_event` callback in `tools.py` | Click handler calls `render_*()` |
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

---

## DES-028: Screenshot Capture — Framebuffer Access

**Date:** 2026-05-12
**Status:** IN PROGRESS
**Topic:** How the display server captures its own rendered output as a PNG for agent introspection

### Motivation

Agents need to see what the display server is rendering — the Pharo "World asForm" pattern. Send a scene, take a screenshot, read the image, diagnose issues. This closes the debugging loop: no human in the loop for visual verification.

### What we built

Protocol: `ScreenshotRequest` / `ScreenshotResponse` following the introspect request-response pattern. The MCP tool (`screenshot`) sends the request; the display server captures on the render thread and returns a file path. The agent reads the PNG via the Read tool.

### What we know

1. **Backend is `Glfw - OpenGL3`** on macOS (confirmed via `hello_imgui.get_backend_description()`). Not Metal, despite macOS having Metal support in imgui-bundle.

2. **`glReadPixels` captures partial content.** Reading from `GL_FRONT` after buffer swap captures the window background color, frame borders, and the Lux watermark — but NOT ImGui widget content (text, sliders, buttons, tables). Reading from `GL_BACK` before swap returns white (empty buffer).

3. **Timing explored:**
   - End of `show_gui` callback (`_on_frame`): GL_BACK is empty — ImGui hasn't rendered draw data to GL yet.
   - `after_swap` callback: GL_FRONT has background but not widgets.
   - Both timings produce incomplete captures.

4. **`hello_imgui.final_app_window_screenshot()`** only works after `run()` exits (confirmed by reading `imgui_bundle/_patch_runners_add_save_screenshot_param.py`). Not usable at runtime.

5. **`CGWindowListCreateImage` (macOS Quartz)** hangs when called from the render thread. Would need to run in a separate thread, but the window ID lookup requires Quartz framework access.

6. **`pyobjc-framework-Quartz`** added to `[display]` extras for the CG approach but not yet successfully used.

### Source investigation (hello_imgui C++)

Read `~/Coding/hello_imgui/` source:

1. **`AppWindowScreenshotRgbBuffer()` exists** (`hello_imgui_screenshot.h:25`). This is a **runtime** screenshot function — distinct from `FinalAppWindowScreenshotRgbBuffer()` which only works at exit. It calls `GetAbstractRunner()->ScreenshotRgb()`.

2. **`OpenglScreenshotRgb()`** (`opengl_screenshot.cpp:14`) is the GL implementation. It calls `glReadPixels` on `GL_RGB` with dimensions from `ImGui::GetDrawData()->FramebufferScale`. It has an explicit assert: "Cannot be called from show_gui() since that runs between NewFrame and Render."

3. **The render loop order** (`abstract_runner.cpp:1240-1427`):

   ```text
   ImGui::Render()                          // line 1240
   Impl_RenderDrawData_To_3D()              // line 1241 — GL draws
   Impl_SwapBuffers()                       // line 1247
   AfterSwap() callback                     // line 1427
   ```

   The screenshot must happen between `RenderDrawData` (1241) and `SwapBuffers` (1247). There is NO callback at that exact point. `BeforeImGuiRender` fires before line 1240 (too early). `AfterSwap` fires after line 1247 (back buffer is gone).

4. **`AppWindowScreenshotRgbBuffer` is not exposed in Python.** Only `final_app_window_screenshot` and `final_app_window_screenshot_framebuffer_scale` are bound. The runtime function exists in C++ but has no Python binding in imgui-bundle 1.92.600.

### Root cause

`glReadPixels` from any callback available to us reads an empty or partially-composited buffer because the actual widget rendering (`ImGui_ImplOpenGL3_RenderDrawData`) happens after our `show_gui` callback returns and before the next callback we can hook. The `after_swap` callback is too late — the back buffer was swapped.

### Rejected approaches

| Approach | Why rejected |
|----------|-------------|
| `glReadPixels` from `show_gui` | Too early — between NewFrame and Render, back buffer empty |
| `glReadPixels` from `after_swap` | Too late — back buffer swapped, front has incomplete content |
| `GL_FRONT` after swap | Captures background/chrome but not widget content |
| Force `RendererBackendType.open_gl3` | Unnecessary (already using GL3) and changes rendering for one feature |
| `final_app_window_screenshot()` at runtime | Only works after `run()` exits |
| `CGWindowListCreateImage` on render thread | Hangs (Quartz APIs deadlock during GL render loop) |
| `screencapture -l` shell-out | Shell-out is not the right approach |

### Path forward

1. **Request Python binding for `AppWindowScreenshotRgbBuffer()`** from imgui-bundle. Open an issue or PR at `pthom/imgui_bundle`. This is the correct API — it exists in C++, handles the timing correctly, and works on all backends.

2. **Alternative: add a `before_swap` or `post_render` callback to hello_imgui** that fires between `RenderDrawData` and `SwapBuffers`. This would let us call `glReadPixels` at the right time without needing the C++ screenshot function.

3. **Alternative: `CGWindowListCreateImage` from a background thread** with the result communicated back via queue. The hang on the render thread may be a main-thread-only Quartz restriction. This is the OS-level approach that works regardless of GL timing.

---

## DES-029: Protocol Dataclasses — `frozen=True, slots=True` on Wire Types

**Date:** 2026-05-16
**Status:** ACCEPTED

### Problem

All 48 `@dataclass` decorators in `protocol/elements.py` (27) and
`protocol/messages.py` (21) were bare — no `frozen`, no `slots`. Protocol
types are the JSON wire format between agents and `luxd`. Three call sites
in the codebase mutated protocol instances directly via `hasattr`/`setattr`
after construction, treating them as mutable state holders rather than
messages. This made the types semantically incorrect for their actual role
and prevented the type system from catching accidental mutation.

### Decision

All protocol element and message dataclasses use `@dataclass(frozen=True, slots=True)`.

**`frozen=True`:** Prevents attribute reassignment after construction.
Any code that mutates a protocol instance now raises `FrozenInstanceError`
at the site of the bug rather than silently corrupting state.

**`slots=True`:** Generates `__slots__` from declared fields. Prevents
dynamic attribute injection (`obj.bogus = x` raises `AttributeError`).
Reduces per-instance memory by eliminating `__dict__` (relevant at scale:
one element instance per rendered widget per frame).

### Mutation sites refactored

Three call sites previously mutated protocol instances and were refactored
to `dataclasses.replace()`:

| Site | Before | After |
|------|--------|-------|
| `elements.py` tooltip stamping | `elem.tooltip = tooltip` | `replace(elem, tooltip=tooltip)` |
| `scene/manager.py` field patching | `setattr(elem, k, v)` | `replace(elem, **valid)` |
| `display/server.py` scene_id stamping | `event.scene_id = id` | `replace(event, scene_id=id)` |

The `_apply_patch_set` refactor also adds field validation:
`dataclasses.fields(elem)` is used to filter patch keys before calling
`replace()`, so unknown field names log a warning and are dropped rather
than raising `TypeError`.

### `__post_init__` with `object.__setattr__`

`TableFilter` uses `InitVar[int | list[int]]` to compute a derived
`_column: list[int]` field. With `frozen=True`, `__post_init__` cannot
assign directly. The correct pattern — and the one the dataclass machinery
itself uses — is `object.__setattr__(self, "_column", col)`. Validation
runs before this assignment so the instance is never partially initialized
on error.

### Alternatives rejected

| Alternative | Why rejected |
|-------------|-------------|
| Keep mutable | Accidental mutation is undetectable; wire objects are commands, not state holders |
| `frozen=True` without `slots=True` | No memory benefit; dynamic attribute injection still possible |
| `NamedTuple` | No default field values; less ergonomic; dataclass ecosystem compatibility |
| `TypedDict` | No methods; no `__post_init__`; loses the `replace()` API |

### Consequence

Adding `frozen=True` revealed that the protocol types were being used as
both wire messages and scene graph nodes — two roles with opposite
mutability requirements. See DES-030.

---

## DES-030: Three-Layer Type Model — Wire / Scene Graph / Snapshot

**Date:** 2026-05-16
**Status:** PROPOSED

### Problem

DES-029 making protocol types frozen exposed a structural contradiction:
the same dataclass instances are used as wire messages (correct: immutable,
short-lived) and as retained scene graph nodes (wrong: need to be mutable,
long-lived). The `apply_update` path works around this by calling
`dataclasses.replace()` to produce new frozen instances and swapping them
into the scene's `elements` list — while the `elements` list itself is
mutable because it is stored in a frozen `SceneMessage`. The
frozen/mutable boundary is incoherent: the message is frozen, the list
inside it is mutable, the elements inside the list are frozen, lists
inside those elements are mutable.

The `hasattr`/`setattr` patterns documented in
`docs/oo-refactor/dynamic-access-design.md` are a further symptom: they
exist because the code needs to apply untyped `dict[str, Any]` patches to
objects that have no typed update interface.

### Decision

Three distinct data roles require three distinct type layers. The current
codebase implements Layer 1. Layers 2 and 3 are the target architecture.

**Layer 1 — Wire types** (current; `frozen=True, slots=True` correct)

Protocol dataclasses in `protocol/`. Created by the agent, deserialized
by `luxd`, applied to scene graph, discarded. Short-lived commands. The
`frozen` constraint is correct because these are value objects in the
strict sense: no ownership, compared by value, stateless after
construction.

**Layer 2 — Scene graph nodes** (target; mutable correct)

Mutable classes in `scene/`, one per element kind, owned exclusively by
`luxd`'s `SceneManager`. Updated incrementally by incoming wire commands.
Each node exposes a typed `apply(patch: SliderPatch) -> None` method
rather than accepting `dict[str, Any]`. No `hasattr`, no `setattr`, no
`dataclasses.replace(**unknown_dict)` — the type system enforces which
fields can be patched on which element kind.

**Layer 3 — Display snapshot** (target; `frozen=True` correct for a different reason)

Immutable `DisplaySnapshot` produced from the current scene graph state
and pushed to `lux-display` over the Unix socket IPC. The renderer
consumes it and discards it. `frozen=True` is correct here not because
the data is conceptually immutable, but because the snapshot crosses a
concurrency boundary: the renderer reads it during a frame while the hub
may be computing the next one. An immutable snapshot eliminates the race
without a lock.

### Update rate vs. refresh rate

`luxd` determines the update rate (agent-driven, bursty: it pushes a new
snapshot when agents cause changes). `lux-display` owns the refresh rate
(hardware-driven: 60 fps, 16 ms/frame). The snapshot is the decoupling
mechanism. The renderer never waits for the hub; the hub never waits for
the renderer to finish a frame.

This separation is currently incomplete: the display and hub share one
process and the socket poll runs inside the ImGui frame loop. The
three-process split (DES-022 / `docs/architecture/target/topology.md`) makes
the rate decoupling physical.

### Typed patches per element kind

The `UpdatePatch.set: dict[str, Any]` wire field is the correct level of
flexibility for the wire protocol — agents send field subsets, the runtime
applies them. The problem is that the application of these patches reaches
all the way into the scene graph without a typed intermediary. The scene
graph layer translates the wire patch into a typed call:

```python
# Wire layer decodes the dict into a typed patch object per element kind
patch = SliderPatch(value=0.5, label="Speed")
# Scene graph node applies it via a method — no dict, no reflection
scene_manager.get_node("slider-1").apply(patch)
```

This is a protocol-level change requiring updates to `UpdateMessage` wire
format, the agent SDK, and the scene graph layer simultaneously.

### What this is not

This ADR does not decide the implementation order or timeline. It records
the design direction so that future changes to scene management,
serialization, and the hub architecture are made with awareness of where
they fit in the three-layer model. Any code that adds new mutation paths
to frozen protocol types, or that adds new `hasattr`/`setattr`/`getattr`
calls, is moving in the wrong direction.

### Relationship to other decisions

- DES-023 (dependency layering): the wire/scene graph split aligns with
  the `[display]` extras boundary — wire types have no heavy deps, scene
  graph nodes may.
- DES-022 (workspace model): the hub-as-policy-layer owns the scene graph;
  the display-as-renderer owns nothing but its framebuffer.
- `docs/oo-refactor/dynamic-access-design.md`: detailed treatment of the
  dynamic attribute access debt and the typed patch path forward.

---

## DES-031: Domain Model Across All Three Tiers — Not Just a JSON Renderer

**Date:** 2026-05-22
**Status:** ACCEPTED
**Decided by:** the operator
**Companion plan:** `docs/oo-refactor/migration-plan.md`

### Problem

DES-030 established the three-layer *type* model (wire / scene graph /
snapshot). The remaining question is structural: across the three
*process* tiers (Lux applications → Lux hub → Lux display), is the right
shape:

- **(a)** A well-factored procedural JSON renderer — small files, pure
  per-kind render functions, no Domain class, no Update bus, no Event
  vocabulary. The wire protocol and the 24 element kinds are the
  contribution; everything else is plumbing.
- **(b)** A live domain model with state + behavior together — Element
  Composite tree, Client ownership, semantic Updates, Event log, a
  `Display` class that mediates writes — realized identically in all
  three tiers, with the IPC boundary being a serialization concern, not
  a structural one.

The migration-method review (recorded in `migration-plan.md`) surfaced
this as a real architectural fork. Three architect agents reviewed the
migration *path*; one of them (`rop`, Plan 9 simplicity school) went
beyond scope and argued for (a) — that the domain model is "Smalltalk-image
cosplay built on top of a JSON renderer that already works."

The operator is the design authority and resolved the question
explicitly: **(b).** This ADR records that decision and its rationale so
the question doesn't get relitigated.

### Decision

Lux pursues the domain model across all three tiers, as specified in
`docs/architecture/target/ui-model.md`. Live Elements with identity and
ownership. Updates as five typed semantic primitives. Events emitted on
every state change. A `Display` class that holds Scenes and Clients,
applies Updates, validates invariants, emits Events. The same domain
model lives in the hub (`hub_display`) and the display server
(`wire_display`); the codec at the IPC boundary serializes Updates and
Events between them.

This decision applies to all three tiers — application, hub, display —
not just to the hub.

### Rationale (operator's reasoning, recorded verbatim in substance)

**1. Testability is not a trivial concern for an event-driven GUI
system.** A procedural codebase can be tested by writing many unit tests
against many small functions. That is not equivalent to having a
DOM-equivalent that can be observed fully. The latter lets a test
construct a `Display`, apply a sequence of Updates, query the resulting
tree via `snapshot()`, assert on element identities and ownership,
verify event emission order, and exercise failure paths — all in one
process, without ImGui, without sockets. A collection of render
functions does not give us that. The single-runtime test from
`docs/architecture/target/ui-model.md` §"Testability" is the discriminating example:

```python
display = Display()
alice_id = display.connect_client(name="alice")
bob_id = display.connect_client(name="bob")
display.apply(alice_id, AddElement("s1", parent_id=None,
                                   element=Button(id="b1", label="hi")))
refused = display.apply(bob_id,
                        SetProperty("s1", "b1", "label", "evil"))
assert isinstance(refused, OwnershipError)
assert display.snapshot("s1").element("b1").label == "hi"
```

That test is unwritable in a procedural design. The cost of writing
many small function tests is real but is not interchangeable with the
ability to assert behavioral invariants against a live, observable
model.

**2. ImGui is direct-mode for the *display* — but the hub and Lux-native
applications are not.** It is true that `lux-display` consumes a scene
description and re-issues ImGui calls every frame. That tier can in
principle remain stateless and dumb. The hub (window manager) cannot:
it owns scene composition over time, client ownership, menu registry,
event routing — all of which are stateful concerns where behavior
should travel with the data. Lux-native applications (the Beads Browser
today, more in the future) are unambiguously stateful: they hold
model state, react to events, mutate scenes incrementally. Treating all
three tiers as "JSON in, ImGui out" is correct for the display but
incorrect for the hub and wrong for applications. Forcing the design to
the lowest-state tier impoverishes the upper two.

**3. The same domain model in all tiers makes process boundaries an
implementation detail, not a structural one.** If `Display`, `Update`,
and `Event` are the contract, then objects and message-passing within
one process are trivially equivalent to IPC calls across processes.
The codec at the boundary serializes the same Updates and the same
Events. This means single-process testing is equivalent to distributed
testing. Single-process debugging is equivalent to distributed
debugging. The same test that exercises the model in one process
exercises the IPC path when the tiers are split — the only difference
is the codec. This is a load-bearing property: without it, the
multi-process architecture either grows a parallel test infrastructure
or remains untested across the boundary. With it, every test we already
write becomes a distributed test for free.

**4. There is no way to reason about a system as a random collection of
modules and functions.** A mental model of a system requires a
simulation — a small set of nouns (Element, Scene, Client, Update,
Event, Display) with verbs that act on them in known ways. The
operator's experience across many systems is that procedural codebases
without this structure don't scale to teams or to time. Newcomers
can't build a working model; long-term maintainers grow tribal
knowledge that doesn't survive turnover. The domain model is the
simulation that makes the system thinkable.

### Alternatives considered

**Alternative A — Procedural well-factored renderer (rop's "Method Z").**
Just split the big files. Extract per-kind render functions into one
file per family. No `Display` class. No `Update` bus. No `Event`
vocabulary. The wire protocol stays as-is; whole-scene replacement
remains the primary mutation primitive.

*Why rejected:* See rationale 1-4. Specifically, it gives up the
single-runtime testability property (rationale 1), pins all three tiers
to the lowest-state design (rationale 2), forces the IPC boundary to be
a special case rather than a serialization concern (rationale 3), and
yields a codebase that resists mental modeling (rationale 4). The
efficiency gain — fewer PRs, less code — is real but pays for itself
only if those four properties are not load-bearing. The operator's
judgment is that they are.

**Alternative B — Domain model in the hub only.** Hub gets `Display`,
`Update`, `Event`. Display server stays a dumb renderer. Lux-native
applications keep whatever shape they have.

*Why rejected:* Breaks rationale 3. If only the hub has the domain
model, the boundary to the display server is a special case (some other
serialization format). Tests of the hub are not tests of the
distributed system. Lux-native applications can't share the model.
Half-measure.

### Consequences

**Positive:**

- Tests written against `Display` in one process exercise the same
  semantics that IPC-mediated multi-process deployments will exhibit.
- Invariants (ownership, acyclic tree, typed properties) are enforced
  in one place — the domain layer — and trusted everywhere else.
- The mental model is small and stable: six nouns, six verbs, two
  failure shapes.
- Process split becomes mechanical (PR 13 in the migration plan) because
  the codec is the only thing that differs across the boundary.

**Negative:**

- More code than a procedural design. The cost is paid in PRs 1-5 of
  the migration plan.
- Element types acquire methods they don't have today; the wire codec
  is no longer a separate concern (it's a method on the class —
  PY-OO-7).
- The OO ratchet becomes harder to satisfy as the surface grows. The
  discipline is non-negotiable; the migration plan handles it
  family-by-family so each PR's ratchet check is bounded.

### What this is not

This ADR does not specify implementation order — that is the migration
plan's job. It does not redefine the wire protocol — `docs/architecture/target/ui-model.md`
already specifies that. It does not commit to a single test framework
— the test pyramid in the migration plan does that.

### Authority

The decision is the operator's. The reasoning is the operator's. This
ADR records what was decided so that the question — *should this just
be a procedural JSON renderer?* — does not get reopened by a future
reviewer, agent, or specialist. If new evidence appears that the
domain model is wrong, the path is to propose a new ADR that
supersedes this one with citation of the evidence. The path is **not**
to relitigate the architectural target inside a migration-method
review.

### Relationship to other decisions

- DES-022 (workspace model): hub-as-policy-layer is realized by
  `hub_display` holding the authoritative `Display` instance.
- DES-029 (`frozen=True` wire types): wire layer remains immutable;
  scene-graph nodes are mutable per DES-030; this ADR adds the
  observation that Elements should carry behavior, not just data.
- DES-030 (three-layer type model): orthogonal — DES-030 is about
  *data shape* at each layer; DES-031 is about *behavior and
  invariants* across the tiers.
- `docs/architecture/target/ui-model.md`: the algebra this decision
  commits to realizing.
- `docs/architecture/target/topology.md`: the topology this decision
  preserves; the codec at the IPC boundary is the only structural
  difference between the tiers.
- `docs/oo-refactor/migration-plan.md`: the executable path to
  realize this decision.

## DES-032: Element Owns Behavior, Not I/O — Codec Methods Move Off the Class

**Date:** 2026-05-23
**Status:** ACCEPTED
**Decided by:** the operator
**Companion doc:** `docs/architecture/archive/io-model.md`

### Problem

PR 1 (`lux-b14i`, #186) and PR 2 (`lux-i84j`, #187) shipped the basics
and inputs element families with codec methods — `to_dict` and
`from_dict` — defined on the Element class itself. The pattern was
justified by PY-OO-5 (state + behavior on the class) and PY-OO-7 (no
fake-OO module-level helpers next to dataclasses), and it was a strict
improvement over the procedural module helpers that preceded it.

The principle is consistent with DES-031: Element is a domain object,
not a JSON renderer. But applying that principle uniformly raises a
sharper question.

If "Element imports `imgui` directly" is wrong because it couples the
domain object to one render surface, then **"Element imports `json`-shaped
dicts directly" is wrong by the same logic** — it couples the domain
object to one wire format. The codec methods on the class are a
narrower version of the same coupling we forbid elsewhere.

PR 1 and PR 2 over-applied PY-OO-5: codec is an I/O concern, not
domain behavior. State + behavior on the class means *domain* behavior —
what happens on click, on minimize, on maximize, on drag, on value
change — not *transport* behavior.

### Decision

The Element class owns:

- **State** — fields (id, label, value, children, ...)
- **Behavior** — domain methods (`on_click`, `on_drag`, `on_minimize`,
  `on_maximize`, `on_value_change`, ...) that encode what user actions
  *mean* for this element
- **Composition** — `_children()` hook for composites; empty tuple
  for leaves
- **Render template** — inherited from the `Element` abstract base via
  the template method pattern; delegates to an injected
  `RendererFactory`

The Element class does NOT own:

- `to_dict` / `from_dict` (or any other format-specific codec)
- Direct render code for any surface
- Direct emission to any wire channel — interactions go through
  behavior methods (`on_click` etc.) which decide what (if anything)
  to emit through an injected `Emit` callable

Wire-decode moves to a per-format Decoder family. Rendering moves to
a per-surface Renderer family. Both injection points are abstract
Protocols the Element imports; no concrete I/O imports survive on
the Element side.

### Rationale

**1. Symmetry is the principle.** Input format and output surface are
structurally identical concerns: both external, both pluggable, both
have multiple legitimate implementations. The argument that justifies
"no `imgui` import on Element" justifies "no `json` import on Element"
by the same shape. Splitting one off and leaving the other on the
class is incoherent.

**2. Behavior is the missing piece for real applets.** A button is
not just "a thing that emits when clicked" — it is "a thing that
KNOWS what its click means." A modal dialog's OK button closes the
modal and passes form state back. A window remembers its position
across drags. A tree node knows how to expand and collapse. None of
that lives on a renderer; all of it lives on the element. Without
behavior on Element, every applet author re-implements the same
patterns outside the tree with ad-hoc state-threading. With behavior
on Element, applets compose naturally through the Composite pattern.

**3. The PR 1+2 placement of codec on the class was justified
locally but wrong in aggregate.** Locally, putting `to_dict` on
`ButtonElement` is better than `_button_to_dict(elem)` in a module
file — PY-OO-7 is correct about that. But the right answer is not
"codec on the class" — it is "codec is not a method of the domain
class at all." The right factoring puts codec in a per-format
Decoder family, restoring full separation between domain and I/O.

**4. The migration from PR 1+2 state is bounded.** The codec methods
on the class are a small surface (one `to_dict`, one `from_dict` per
Element kind). Moving them to per-format Decoder classes is
mechanical for the JSON case (the only format we use today) and
opens the door to msgpack / cbor / protobuf families when those
become valuable.

### Alternatives considered

**Alternative A — Keep codec on the class.** Justification: PY-OO-5
plus a single-format world (we only ever speak JSON). Lower file
count, no abstract Decoder Protocol needed.

*Why rejected:* Inconsistent with DES-031's reasoning when applied
to render. The "single-format world" assumption is the same shape
as "single-surface world" that we already rejected for rendering.
Multi-format inputs (JSON for Python agents, msgpack for Go, cbor
for embedded) is a near-future capability the symmetric design
enables for free; the asymmetric one blocks.

**Alternative B — Element is a transport struct (no behavior at all).**
Plain dataclass, renderer does all the work including click handling.
Codec stays on the class as the only "behavior."

*Why rejected:* This is the procedural-Python-with-dataclasses
anti-pattern PR 1 and PR 2 were tearing out. It contradicts DES-031
directly and produces the "applet authors re-implement everything
outside the tree" failure mode.

### Consequences

**Positive:**

- Element is a true domain object — state, behavior, composition. The
  noun in the model, not a transport detail.
- Multi-format inputs become free. Adding `MsgpackDecoderFactory` is
  purely additive; no Element changes.
- Multi-surface outputs become free. Adding `HtmlRendererFactory` is
  purely additive; no Element changes.
- Test renderers (`RecordingRendererFactory`, `NullRendererFactory`)
  unlock automated coverage of the render layer for the first time.
- Behavior methods on Element compose with the Composite pattern —
  applets author behavior on per-kind subclasses, not in separate
  event-handling layers.
- **Direct construction is a free consequence.** Because
  `renderer_factory` and `emit` are injected at constructor time
  (not threaded through a Decoder), any Python code that has both
  in scope can construct Elements directly. This includes (a) tests
  that build Elements headlessly without serializing through JSON,
  (b) native Python applets that import the `punt_lux` library
  rather than write JSON manually, and (c) embedded scenarios where
  the same process holds the applet, hub, and display. The Decoder
  family is the path for *crossing trust boundaries* (untrusted
  input, foreign-language agents); it is not the only path for
  Element construction.

**Negative:**

- The PR 1+2 codec-on-class pattern must be migrated to per-format
  Decoder families. This is a structural change to every per-kind
  module, even though the migration is mechanical.
- File count rises — each format adds N per-kind decoder classes
  (where N is the element-kind count). The cost is bounded by the
  number of formats we actually support.
- The construction signature for Element subclasses gains two
  required keyword args (`renderer_factory`, `emit`). Wire-decode
  is the one place that has to thread them in; internal callers
  (tests, applets, hub) already have both in scope from Display
  startup or library initialization.

### What this is not

- This ADR does not specify the migration order — that is a separate
  migration-plan update.
- This ADR does not commit to a specific Encoder family for the
  output side of the wire (`Element → dict`). **SUPERSEDED by
  DES-034:** Encoder family is committed as a peer to Decoder. The
  rest of this bullet is preserved for historical context; the actual
  Encoder family lands in the migration PR that ships the
  connection-layer cleanup.
- This ADR does not change the Element vocabulary, the Update sum
  type, the Event sum type, or any other domain-layer specification
  established in DES-031 and `docs/architecture/target/ui-model.md`.

### Authority

The decision is the operator's, reached through design discussion in
the post-PR-2 session that produced `docs/architecture/archive/io-model.md`.
The reasoning that PR 1 and PR 2 over-applied PY-OO-5 is the
operator's. This ADR records the correction so the question — *should
codec live on the Element class?* — does not get reopened and so the
migration of codec off the class proceeds with explicit authority.

### Relationship to other decisions

- DES-031 (domain model across tiers): this ADR is a direct consequence.
  DES-031 says Element is a domain object; DES-032 names what that
  means at the I/O boundary specifically.
- DES-030 (three-layer type model): unchanged. The wire layer still
  has typed shapes; this ADR moves the codec that produces them off
  the domain class.
- DES-029 (`frozen=True` wire types): partially affected. Element
  subclasses move from `@dataclass(frozen=True, slots=True)` to ABC
  inheritance with `__new__`-pattern construction. The immutability
  invariant is preserved by convention (no mutation methods on
  Element subclasses) rather than by `@dataclass(frozen=True)`. A
  follow-up ADR will specify the new immutability discipline if
  this proves to need teeth beyond convention.
- DES-033 (Renderer and Decoder families): the next ADR, which
  specifies the I/O architecture this one commits to.
- `docs/architecture/archive/io-model.md`: the long-form architecture
  document this ADR is the decision of.

## DES-033: Renderer and Decoder Families with Asymmetric Cardinality

**Date:** 2026-05-23
**Status:** ACCEPTED
**Decided by:** the operator
**Companion doc:** `docs/architecture/archive/io-model.md`

### Problem

DES-032 established that Element owns behavior and not I/O. The
follow-on question is structural: *how* do the two I/O sides get
plugged in, and what is the runtime cardinality?

Three design questions need explicit resolution:

1. What shape do the per-surface render and per-format decode
   families take? One god-object Surface with a method per element
   kind, or per-kind classes per family?
2. How do the registries dispatch? At construction time, at render
   time, at message-receive time, or some combination?
3. What is the runtime cardinality? One renderer + one decoder per
   Display, or many?

The first two were converged in the io-model design discussion
([`docs/architecture/archive/io-model.md`](docs/architecture/archive/io-model.md)). The third is
asymmetric in a way that affects the application wiring.

### Decision

**Per-surface Renderer family.** One `RendererFactory` per render
surface (ImGui, HTML, Recording, Null). Each factory owns a
collection of per-kind Renderer classes (one per Element kind:
`ImGuiButtonRenderer`, `HtmlButtonRenderer`, etc.). The factory
dispatches by Element type via `match` and returns the
appropriate per-kind Renderer instance bound to the element. The
`Renderer` Protocol is small: `render()` for leaves, `begin()` /
`end()` for composites. The Composite recursion lives in the
`Element.render` template method, not in the Renderer.

**Per-format Decoder family.** Structurally identical: one
`DecoderFactory` per wire format (JSON, msgpack, cbor, protobuf).
Each factory owns per-kind Decoder classes that read wire bytes
into fully-constructed Elements with `renderer_factory` and `emit`
injected at construction.

**Module-level registries** select the family by key:

- `Renderers.getRendererFor(Surface.IMGUI) → RendererFactory`
- `Decoders.getDecoderFor(WireFormat.JSON, renderer_factory, emit) → DecoderFactory`

`Surface` and `WireFormat` are constrained enums — no behavior, just
discriminators.

**Cardinality is deliberately asymmetric:**

| | Selected when | Lifetime | Count per Display |
|---|---|---|---|
| `RendererFactory` | Display startup | process | 1 |
| `Decoder` | client connect (format detected/negotiated) | connection | N |

A single Display has one rendering surface but accepts many
concurrent client connections, each potentially speaking a
different wire format. All decoders thread the same
`renderer_factory` and `emit` into the Elements they construct, so
every Element regardless of input origin renders through the same
output and emits to the same channel.

### Rationale

**1. Per-kind, per-family classes avoid the god-object Surface.** An
earlier draft proposed a `Surface` Protocol with one method per
Element kind (`surface.button(...)`, `surface.text(...)`,
`surface.slider(...)`). That collapses to a 30+ method interface
that every surface must implement in full. Per-kind classes
distribute the family knowledge across small, focused units. Each
class is ~30 lines and tells you exactly what an ImGui Button does
or what an HTML Group emits.

**2. The Composite pattern lives on Element, not on Renderer.** The
GoF Composite requires the same operation method on Component, Leaf,
and Composite — implemented via inheritance. By placing `render()`
on the Element abstract base as a template method, the Composite
shape is on the domain object. The Renderer Protocol can be
narrower (just the drawing primitives) without needing to
reproduce the composite recursion. Recursion happens through
`Element.render` calling itself on children.

**3. Registries (Renderers, Decoders) decouple selection from
construction.** The application wiring code calls the registry with
a key and gets a factory; the factory is then passed where it's
needed. The Element class never imports any concrete factory; it
imports only the abstract Protocols. New families register by
extending the registry's `match` block.

**4. The cardinality asymmetry is structural and intentional.** A
Display is a singular thing — it draws to one surface. Adding a
second concurrent surface would be a second Display. Conversely,
multi-client multi-format input is the entire point of Lux as a
shared visual surface — agents in different languages or runtimes
must be able to participate. The registries make this trivial: the
connection handler negotiates a format per connection and gets the
right decoder; the rendering loop never knows or cares which
client's elements it's drawing.

**5. The renderer reports interactions back to Element behavior;
the Element decides what to emit.** Per DES-032, behavior lives on
Element. ImGui detects "the user clicked the button" and calls
`elem.on_click()`; the Element runs its domain behavior, which for
a button typically emits an InteractionMessage to the injected
`emit` channel. HTML detects clicks asynchronously via a JS
handler and websocket round-trip; the same `elem.on_click()`
method is the destination. The renderer's responsibility is
*surface-idiom detection*, not domain decisions.

### Alternatives considered

**Alternative A — God-object Surface with one method per element
kind.** A single `Surface` Protocol that every backend implements
in full.

*Why rejected:* Forces every surface to know about every element
kind; one new element kind requires a coordinated update to every
surface. Per-kind, per-family classes localize the change.

**Alternative B — Visitor pattern with `accept(visitor)` on
Element.** External dispatch where the renderer is a Visitor that
walks the Element tree.

*Why rejected:* Adds `accept()` method to every Element solely for
dispatch. Doesn't compose well with behavior methods (`on_click`,
`on_drag`) that live on the same class. Template method on the
Element base is cleaner and reads as the Composite the pattern
literally is.

**Alternative C — Parallel Renderer tree mirroring Element tree
(no Element render method).** Element stays inert data; a factory
walks the Element tree and builds a parallel Renderer tree where
each Renderer node knows its element and surface. Renderer tree
has the Composite shape.

*Why rejected:* Sneaks Element back into the
no-behavior-on-the-class pattern PR 1 and PR 2 were eliminating.
Forces a rebuild story for the Renderer tree on every Element
mutation. Doubles the in-memory tree. By DES-031 + DES-032, the
behavior belongs on Element; the Renderer tree shadow is
unnecessary.

**Alternative D — Dispatcher object separate from Renderer.** A
Dispatcher class holds the per-kind dispatch table and is passed
into Element.render. Element.render delegates to dispatcher,
dispatcher delegates to per-kind renderer.

*Why rejected:* Three objects (Element, Dispatcher, Renderer) for
what is structurally two responsibilities (Element's render +
per-kind drawing). The `RendererFactory` callable IS the dispatch
(`factory(elem) -> Renderer`); no separate Dispatcher class needed.

**Alternative E — Symmetric cardinality (one Decoder per Display).**
Force all connected clients to speak the same wire format.

*Why rejected:* The Lux value proposition is multi-language,
multi-runtime agents collaborating on a shared display. Forcing
format uniformity rules out polyglot agents at the architectural
level for no benefit.

### Consequences

**Positive:**

- Adding a new render surface (HTML, recording, EventTracking)
  requires a new factory and per-kind classes — no Element changes,
  no Decoder changes, no registry changes beyond one `match` arm.
- Adding a new wire format (msgpack, cbor, protobuf) requires a new
  decoder family — no Element changes, no Renderer changes, no
  registry changes beyond one `match` arm.
- Test renderers (Recording, Null, EventTracking) unblock the
  rendering-layer test gap that's existed since PR 0 — every render
  path becomes assertable headlessly.
- Multi-client multi-format input becomes a configuration
  decision, not an architecture project.
- Click handling, drag handling, value-change handling all live in
  one place per Element kind, on the Element subclass.

**Negative:**

- More files. Per-surface families plus per-format families
  multiply per-kind classes by `(surfaces × kinds) + (formats × kinds)`.
  Today: 24 kinds × 1 surface (ImGui) × 1 format (JSON) =
  48 per-kind classes. Five years out with three surfaces and two
  formats: 24 × 3 + 24 × 2 = 120 per-kind classes. Each is small
  (~30 lines) but the directory grows.
- Connection-layer wiring gains complexity — format negotiation,
  per-connection decoder lifecycle, owner-routing of emit.
- DES-029's `frozen=True` invariant changes shape — see DES-032's
  note on this.

### What this is not

- This ADR does not commit to building HTML, RecordingRenderer, or
  any specific test backend. **SUPERSEDED by DES-034 + migration
  plan PR 3:** RecordingRenderer and NullRenderer are committed
  (DES-034) and built in PR 3 — they are no longer optional. HTML
  remains additive when wanted. The shape that makes additional
  backends drop-in is unchanged.
- This ADR does not specify the migration order from the PR 1+2
  state (codec-on-class, `ElementRenderer` god class, no per-format
  decoders) to the io-model architecture. The migration plan is a
  separate update.
- This ADR does not specify Encoder symmetry. **SUPERSEDED by DES-034:**
  Encoder family is committed as a peer to Decoder. The rest of this
  bullet is preserved for historical context; the actual Encoder
  family lands in the migration PR that ships the connection-layer
  cleanup.
- This ADR does not specify the format-negotiation mechanism (sniff
  first bytes, scheme tag, per-port convention, content-type
  header). That is a connection-layer concern, not an Element-design
  concern.

### Authority

The decision is the operator's, reached through design discussion in
the post-PR-2 session that produced `docs/architecture/archive/io-model.md`.
The asymmetric-cardinality observation is the operator's. This ADR
records the architecture so that the question — *how do we plug in
multiple surfaces and multiple wire formats?* — has a single
answer to point at and so that the implementation is bounded.

### Relationship to other decisions

- DES-031 (domain model across tiers): this ADR specifies the I/O
  shape that the domain model demands.
- DES-032 (Element owns behavior, not I/O): direct precursor. This
  ADR is the architecture that realizes DES-032's principle.
- DES-030 (three-layer type model): wire layer is now produced by
  Decoder families and consumed by Encoder families if added; the
  type shape is unchanged.
- `docs/architecture/archive/io-model.md`: the long-form architecture
  document this ADR is the decision of. ADR records the decision;
  io-model.md records the design in detail.
- `docs/architecture/target/topology.md`: when PR 13 of the migration
  plan splits `lux-display` into its own process, the cross-process
  IPC is one specific Decoder family (whichever format the hub
  serializes Updates and Events into) on each side of the boundary.

## DES-034: IPC and Rendering Are Decoupled — Renderer vs Encoder Distinction

**Date:** 2026-05-23
**Status:** ACCEPTED
**Decided by:** the operator
**Companion doc:** `docs/architecture/archive/io-model.md`

### Problem

DES-031 and DES-032 establish that Lux is a domain model living across
three tiers (applet, hub, display). The remaining structural question:
how do state changes propagate from applet through hub to display, and
how does rendering fit in? Two confusable framings:

- **(a)** Rendering propagates through IPC. Each tier has a "renderer"
  that, when `elem.render()` is called, ships a render request to the
  next tier (RemoteRenderer pattern). The display's renderer terminates
  by drawing pixels.
- **(b)** IPC carries state-change messages only; rendering is a
  per-tier concern. Each tier holds its own `Display` instance with
  the current scene state; tiers stay in sync by serializing Updates
  across IPC. Rendering happens locally in whichever tier has a render
  loop (display tier only in the default deployment).

The earlier io-model drafts conflated (a) and (b) by using the word
"Renderer" loosely. Post-PR-2 design discussion resolved this.

### Decision

(b). IPC carries **state-change messages** — Updates and Events. IPC
does NOT carry render calls. Each tier holds its own `Display` and its
own copy of the scene state; tiers stay synchronized by applying
Updates that flow across IPC boundaries.

Rendering is a per-tier concern. A tier that has a render loop calls
`scene_root.render()` against its OWN `Display`'s scene with its OWN
`RendererFactory`. The default deployment has a render loop only in
the display tier (lux-display, ImGui main loop). The hub and applet
tiers have no render loop; they have message loops that propagate
Updates and Events.

To prevent the same word from covering two distinct responsibilities,
the design distinguishes:

- **Renderer** — paints a surface. Per-kind, per-surface (e.g.
  `ImGuiButtonRenderer`, `HtmlButtonRenderer`). Lives in tiers that
  have a render loop. Output is pixels (ImGui), HTML strings (Html),
  or a captured event log (Recording).
- **Encoder** — produces wire bytes for the next IPC hop. Per-kind,
  per-format (e.g. `JsonButtonEncoder`, `MsgpackButtonEncoder`). Lives
  in every tier that ships state to a neighbor.

The pair is parallel to the existing **Decoder** family (per-kind,
per-format, reads wire bytes back into Element instances).

The shipping STRATEGY (whole tree vs diffs) is a property of the
downstream surface, not of the tier doing the shipping:

- ImGui downstream → whole-tree shipping every state change. ImGui is
  immediate-mode at the programming interface (its internal diffing is
  its own optimization concern), so re-emitting the whole tree per
  state change is the natural fit.
- HTML downstream → diff-shipping. DOM is retained-mode; full
  retransmission would tear down and rebuild every node.

### Rationale

**1. RemoteRenderer conflates two orthogonal concerns.** Render-call
propagation (on-demand) and state propagation (per state change) have
different cardinalities, different triggers, and different consumers.
A render loop polls every frame; state propagation fires on change.
Marrying them by making render() the IPC trigger forces both behaviors
to share a path that fits neither.

**2. ImGui's immediate-mode interface matches whole-tree shipping.**
ImGui is told the whole tree every frame anyway. Shipping the whole
tree from hub to display on every state change costs the same as
shipping a diff to a stateful client, because the display tier just
hands the latest tree to ImGui's next frame. Diffing only matters
when the downstream is retained-mode (HTML, native DOM).

**3. Renderer-and-Encoder as separate families keeps each focused.**
A renderer's job is "produce surface effects" (draw, emit HTML); an
encoder's job is "produce wire bytes." Lumping them under one name
hides which one a particular class does. Two names, two contracts,
two registries.

**4. Per-tier rendering preserves single-runtime testability** (DES-031
rationale 1). Tests construct an in-process `Display`, exercise it
without IPC, and use a `RecordingRenderer` or `NullRenderer` to assert
on outputs. The render loop in tests is whatever the test drives — no
ImGui context, no display process required.

### Alternatives considered

**Alternative A — RemoteRenderer.** Each tier's `Element.render()` ships
a render request to the next tier via IPC. Display tier's renderer
terminates by drawing.

*Why rejected:* Conflates render-call propagation with state
propagation. Makes the render loop's cadence depend on IPC, which
mismatches how ImGui polls. Tests would have to simulate an IPC chain
to exercise render at all.

**Alternative B — One Renderer concept that covers both surface painting
and wire serialization.** A single Protocol with multiple
implementations: ImGui, HTML, JSON-shipper, msgpack-shipper.

*Why rejected:* Conflates two distinct responsibilities. A JSON shipper
isn't "rendering" — it's serializing. Naming them the same hides the
difference. Two families is two contracts; one family is one fuzzy
contract.

### Consequences

**Positive:**

- The render loop and IPC run in parallel, independently. The render
  loop draws every frame from the local scene state; IPC just keeps
  the local scene state in sync with upstream. The two never collide.
- Renderer family stays focused on surface output (display tier only).
- Encoder family is the dual of Decoder family — same shape, opposite
  direction. Symmetric across IPC boundaries.
- Tests use `RecordingRenderer` / `NullRenderer` against an in-process
  `Display` without any IPC. The single-runtime testability invariant
  from DES-031 is preserved.
- Shipping strategy can vary per downstream surface: ImGui targets get
  whole trees; HTML targets get diffs. The shipping strategy is part
  of the Encoder family's responsibility for the downstream connection.

**Negative:**

- More classes — Renderer family AND Encoder family, both per-kind.
  For N element kinds and S surfaces and F formats, the per-kind class
  count is N×S (renderers) + N×F (encoders) + N×F (decoders). Each
  class is small.
- The applet/hub tiers need a renderer_factory at construction even
  though they never call `elem.render()`. They use `NullRendererFactory`.
  The constructor signature is uniform across tiers; the factory is
  dead weight in tiers without a render loop. Operator accepted this
  cost in exchange for uniform construction.

### What this is not

- This ADR does not specify which formats the Encoder family supports.
  JSON is the only required format today. Adding msgpack, cbor,
  protobuf, cap'n proto is purely additive.
- This ADR does not specify which surfaces the Renderer family
  supports. ImGui is the required surface; RecordingRenderer and
  NullRenderer for tests are required; HTML and any other surface
  ships when there is a consumer.
- This ADR does not specify the diff format for retained-mode
  surfaces. When HTML or another retained-mode surface ships, its
  Encoder family will define its diff shape.

### Authority

The decision is the operator's. Recorded post-PR-2 to prevent the
RemoteRenderer pattern from being re-proposed by a future reviewer or
agent who reads the io-model and reaches for the wrong synthesis.

### Relationship to other decisions

- DES-031: this ADR specifies how state propagates across the three
  tiers that DES-031 established.
- DES-032: this ADR's Renderer vs Encoder distinction sits underneath
  DES-032's "Element does not own its I/O." The Element doesn't know
  about either family; both are injected.
- DES-033: this ADR refines the role of the families DES-033 named.
  Renderer is per-kind-per-surface; Encoder is per-kind-per-format;
  both are dispatched by per-tier registries (`Renderers` and
  `Encoders`).
- `docs/architecture/archive/io-model.md` §"Where rendering happens" — the
  long-form spec.
- `docs/architecture/target/topology.md` — the topology this ADR's IPC
  carries across.

## DES-035: Handler Routing — Ownership, Client Kind, and Pattern Are Three Independent Axes

**Date:** 2026-05-23
**Status:** ACCEPTED
**Decided by:** the operator
**Companion doc:** `docs/architecture/archive/io-model.md`

### Problem

When a user interacts with an element on the display (clicks a button,
types in an input, drags a window), the InteractionMessage must reach
the code that decides what the interaction means. Several earlier
drafts conflated three distinct concerns into one word ("agent-owned"
versus "applet-owned" etc.), producing routing rules that mixed levels
of abstraction. The right architecture separates them into three
independent axes.

### Decision

**Important revision (2026-05-23):** an earlier draft of this ADR
described an "ownership" axis where the hub could forward an
`InteractionMessage` to an owning connection so that connection
could run a custom subclass's behavior. **That model has been
withdrawn.** Per the architecture clarification in
`spikes/io_model_v1/ARCHITECTURE_NOTES.md` A5, applets do **not**
ship custom Element subclasses; they compose standard library
components. All element behavior runs on the hub (which has the
library code). External actors (applets, agents) participate in
interactions by **subscribing to topics published by the hub** when
behavior emits Events.

The revised model has two concerns, not three:

**Axis 1 — Element behavior dispatch (hub-internal).** When an
`InteractionMessage` arrives from display, the hub resolves the
element on `hub_display` and invokes its standard library behavior
method (e.g. `Button.on_click`). The hub's emit handler then
dispatches whatever the behavior emits:

- Typed **Events** (e.g. `ButtonClicked`) → `publish(topic, payload)`
  on the subscription registry.
- Typed **Updates** (e.g. `RemoveElement` emitted by `Dialog.close()`)
  → accept on `hub_display` + encode + ship to display.

There is **no `owner = <connection_id>` case**. The hub does not
forward `InteractionMessage`s to external processes for custom
dispatch.

**Axis 2 — Reaction pattern (downstream of routing).** A connection
that subscribed to a topic decides how to react when notified:

- **Deterministic** — applet's notification handler runs straight
  code (e.g. fetch from DB, format new table, ship `show()` back to
  hub). Same as MCP agent calling tools in a fixed pattern.
- **Agent-escalation** — handler builds a prompt, sends to an LLM,
  waits for response, then ships Updates. An LLM agent's "handler"
  is agent-escalation by construction.
- **Hybrid** — some deterministic work, then escalation.

This axis is downstream of routing — the hub doesn't see it. The
subscriber's process decides how it reacts.

The applet author writes tier-blind code. They subscribe to topics
they care about and react by composing standard components and
calling `show()`. They never override standard element behavior.

### Rationale

**1. Standard components keep the wire vocabulary closed.** If
applets could ship custom subclasses with custom behavior bodies,
either (a) Python code must cross the wire (security and
deserialization nightmare) or (b) the wire encodes a behavior
descriptor the hub interprets (closed vocabulary anyway, just
indirected). The simpler answer: applets compose; the hub runs
library-standard behavior; custom logic lives in applet reactions
to Observer notifications.

**2. Hub routing remains O(1).** Resolve element by id on
`hub_display`, invoke its bound behavior. No cross-process
forwarding for routing.

**3. Applet authors should not write tier-aware code.** Applets
write Python that composes standard scenes and reacts to
notifications. They don't ask "what tier am I in?" The same applet
code runs whether the applet is a separate process or in-process
embedded.

**4. Naming the two axes prevents re-conflation.** "Element
behavior" (hub-internal, library-standard) and "reaction pattern"
(per-subscriber, custom) are distinct concerns. Future proposals
that try to combine them — e.g. "let applets ship Python handler
bodies" — should be rejected at this boundary.

### Alternatives considered

**Alternative A — One routing rule per (ownership, client kind, handler
pattern) combination.** Every combination is a separate rule the hub
matches against.

*Why rejected:* Combinatorial explosion. Most combinations route the
same way at the hub level; only ownership matters at the hub. The
rule-set bloats with no benefit.

**Alternative B — Routing by element class type.** The hub knows what
classes are hub-handled vs forwarded; routes accordingly.

*Why rejected:* Couples the hub to specific element classes. Adding
a new applet-owned class would require hub-side configuration.
Ownership tracking solves the same problem with one bit per element
instance, no class registry.

**Alternative C — Single "agent-owned" / "hub-owned" / "applet-owned"
flag conflating ownership with client kind.** What I originally
proposed in early drafts.

*Why rejected:* Misses the wire client case (Go applet that's not an
LLM agent). Misses the library client with agent-escalation handler
case (Python applet that calls its own LLM). The three-axis
decomposition is what makes those cases coherent.

### Consequences

**Positive:**

- The hub's routing logic is small: lookup owner; if hub, dispatch
  locally; if connection, forward.
- New client kinds (e.g., a future WASM applet) require no hub
  changes; the runtime on the client side handles dispatch.
- Hybrid handler patterns (some deterministic work then escalation)
  fit naturally because pattern is internal to the handler body.
- The applet programming interface is tier-blind. The applet author
  writes one Element subclass with one on_click; the runtime delivers
  events to it regardless of deployment topology.

**Negative:**

- The hub must track per-element ownership for every element, not
  just per-client ownership. (DES-031 already requires this — no new
  cost.)
- Wire clients must implement their own dispatch mechanism. There is
  no library-level convention for non-Python clients beyond "your
  language has a switch statement." This is a feature of wire-client
  flexibility, not a bug, but it does mean a Go applet author writes
  more code than a Python applet author.

### What this is not

- This ADR does not specify how the hub determines ownership at
  element creation time. That mechanism is established in DES-031 —
  the connection that creates an element via `display.apply(...)` is
  recorded as the owner. Hub-shipped elements have `owner = "hub"`.
- This ADR does not specify what the InteractionMessage shape is.
  That is the protocol-element layer's concern.
- This ADR does not commit to any specific handler-pattern
  vocabulary. "Deterministic vs agent-escalation vs hybrid" are
  descriptive labels for the handler-body author; the runtime doesn't
  enforce a category.

### Authority

The decision is the operator's, reached through design discussion
post-PR-2. The three-axis decomposition emerged from the operator
pushing back on the "applet-owned vs agent-owned vs hub-owned" framing
as conflated. Recording the split as an ADR prevents future drift back
to one-axis routing rules.

### Relationship to other decisions

- DES-031: this ADR builds on the ownership model that DES-031
  established (per-element ownership in `Display`).
- DES-032: this ADR's "applet author writes tier-blind code" is a
  consequence of DES-032's "behavior on Element" — the behavior method
  doesn't know about tiers because behavior is just Python code on
  the class.
- DES-033: InteractionMessages routed in this ADR travel on the
  Decoder/Encoder family DES-033 named (with DES-034 specifying the
  Renderer/Encoder distinction within it).
- DES-034: this ADR's routing concerns operate on InteractionMessages
  which are one of the message kinds the Decoder/Encoder families
  handle.
- `docs/architecture/archive/io-model.md` §"Handler routing — three
  independent axes" — the long-form spec.

## DES-036: Observer Pattern at the MCP Boundary

**Date:** 2026-05-23
**Status:** ACCEPTED
**Decided by:** the operator
**Companion doc:** `docs/architecture/archive/io-model.md`

### Problem

The default applet/hub/display deployment uses Lux's own IPC for
inter-tier communication (state changes via Updates, notifications via
Events). At the MCP boundary — between the hub and connected LLM
agents (Claude Code being the canonical example) — a different
protocol applies: MCP defines tools (client → server RPC) and
notifications (server → client push), with no native concept of
Lux's domain-model Updates or Events.

The question is: when an applet (or any internal Lux actor) needs to
**notify an agent** of something the agent should consider — a new
work item is ready, a modal needs confirmation, a form was submitted —
what is the mechanism that crosses the MCP boundary?

Naive options:

- **Polling.** Agent periodically calls a "give me pending events"
  tool. Cheap to implement; high latency; load increases with active
  agents whether or not there's anything to deliver.
- **Direct point-to-point.** Applet has a direct connection to a
  specific agent and pushes notifications across it. Tight coupling;
  applet needs to know which agent exists and how to reach it.
- **Broadcast.** Hub pushes every notification to every connected
  agent. Each agent filters. Wasteful; doesn't scale.

None of these is right. The applet doesn't know which agents exist,
and shouldn't. The agent doesn't know which applets exist, and
shouldn't. They should communicate through a structured intermediary
that preserves loose coupling.

### Decision

The hub implements the **Observer pattern** (Gamma, Helm, Johnson,
Vlissides, *Design Patterns*) at the MCP boundary, with the hub as
the **Subject** and MCP-connected agents as **Observers**.
Subscription is **topic-based**.

**Wire surface (MCP tools and notifications):**

```text
   MCP TOOLS                            MCP NOTIFICATIONS
   (client → server, RPC)               (server → client, async push)
   ──────────────────────               ────────────────────────────

   subscribe(topic: str)                observed(topic: str,
   unsubscribe(topic: str)                       payload: object)
   publish(topic: str,
           payload: object)
```

**Internal hub-side API (hub-process callers only):**

```python
hub.publish(topic: str, payload: Any) -> None
hub.subscribe(topic: str) -> Subscription
```

The hub's emit handler calls `hub.publish(...)` when an Element's
behavior method emits a typed Event. The hub fans the payload out
to every subscribed connection via MCP server-push notifications.
The publisher does not enumerate subscribers; the subscriber does
not know who else subscribed.

**Note (2026-05-23 clarification, see
`spikes/io_model_v1/ARCHITECTURE_NOTES.md` A2 + A3):** `hub.publish`
is **not exposed as a wire API for external processes**. External
apps express intent via typed Updates (`show()`,
`AddElement`/`SetProperty`/`RemoveElement`); the hub's reactive
machinery produces `observed` notifications as a consequence of
accepted state changes. Generalized peer-to-peer pub/sub from
external publishers is a future capability not yet thought
through — see the "What this is not" section below.

**Topic vocabulary** is open. The hub does not pre-declare valid
topics; any string is a valid topic. Conventions will emerge per
applet domain (`bead.queued`, `modal.confirmed`, `form.submitted`,
etc.). Topic namespacing is recommended (dotted prefix) but not
enforced.

### Rationale

**1. Loose coupling matches the actor architecture.** Lux already has
multiple actor types: applets, agents, the hub itself. The Observer
pattern makes them communicable without point-to-point knowledge.
Applets and agents come and go; the hub mediates.

**2. Topic-based fits domain vocabulary, not connection identity.**
Subscribers express interest in WHAT happened, not WHO told them. A
beads-queued notification doesn't care whether it was the beads
dashboard applet or the hub itself that published it. Multiple
observers can subscribe to the same topic for different reasons.

**3. MCP natively supports server-push notifications.** MCP's
notification mechanism (server → client) is unsolicited push. The
agent's runtime (Claude Code, etc.) surfaces incoming notifications
to the LLM, which decides what to do. No polling required.

**4. The internal `hub.publish(...)` API and the MCP wire are dual.**
An applet that publishes via the in-fabric API and an agent that
publishes via the MCP tool produce indistinguishable effects on
subscribers. Subscribers don't know which side the publisher was on.
Same for subscription: in-fabric subscribers and MCP-connected
agents see the same payloads.

**5. The pattern is a textbook Composite-pattern peer.** Composite is
used for the Element family (DES-031, DES-032); Observer is used for
event distribution across loose actors. Both are GoF patterns chosen
for their fit, not for novelty.

### Alternatives considered

**Alternative A — Polling.** Agent calls `pending_events()` periodically.

*Why rejected:* High latency. Wasted work. Doesn't fit the LLM agent's
interactive cycle (agent isn't running a background poll loop;
it's waiting for human prompts).

**Alternative B — Direct point-to-point notification.** Applet
maintains a connection to specific agents.

*Why rejected:* Applets shouldn't know about agents. Coupling
explodes as actor count grows.

**Alternative C — Broadcast.** Hub pushes every notification to every
connected agent.

*Why rejected:* Wasteful. Doesn't scale. Each agent has to filter on
its own, which means each agent has its own filter logic that has to
match the publisher's vocabulary.

**Alternative D — Pub/sub on a separate message bus** (Redis,
RabbitMQ, NATS, etc.).

*Why rejected:* Adds an external dependency for a problem the hub
can solve in-process. The hub is already the single point of
coordination for all Lux actors; it's the natural place for the
subscription registry. If scale ever requires it, swapping the
in-process pub/sub for an external bus is a future change.

### Consequences

**Positive:**

- Applets can notify agents without knowing the agent exists.
- Agents can react to applet events without polling.
- Multiple agents can observe the same topic for different purposes.
- New actor kinds (other applets, observability sinks, monitoring
  tools) can subscribe via the same mechanism with no infrastructure
  changes.
- Same shape works whether the publisher is an applet, the hub
  itself, or another agent.

**Negative:**

- The hub gains a subscription registry and an MCP notification push
  path. New code surface to test and maintain.
- Topic vocabulary is open — convention rather than enforcement.
  Wrong topic names produce silent no-ops (no subscribers); this is
  a debugging burden mitigated by logging unsubscribed publish calls
  at debug level.
- MCP server-push notifications depend on each MCP client's runtime
  surfacing them. Claude Code does; other MCP clients should be
  verified before relying on push semantics.

### What this is not

- This ADR does not commit to a topic vocabulary. Topics are domain
  conventions that emerge per applet.
- This ADR does not commit to a specific subscription persistence
  model. Subscriptions are session-scoped by default (live as long
  as the MCP connection lives). Durable subscriptions across
  disconnects are a future capability if needed.
- This ADR does not commit to a delivery-guarantee model. Default is
  at-most-once via MCP notification (delivery follows the MCP
  transport's reliability). Persistent queues, acks, retries are
  future capabilities if a use case demands them.
- This ADR does not replace the Update/Event flow inside the Lux
  fabric. Updates and Events are how state changes propagate across
  applet/hub/display IPC. Observer notifications are how arbitrary
  domain events propagate across the MCP boundary.
- **Wire kind for `publish` over Lux IPC from external publishers
  (DEFERRED, was committed earlier in this ADR).** An earlier draft
  of this ADR committed to a `PublishMessage(topic, payload)` wire
  kind so a separate-process applet could call `hub.publish` over
  Lux IPC. **That commitment is withdrawn** per
  `spikes/io_model_v1/ARCHITECTURE_NOTES.md` A3. The current model:
  external apps drive state via typed Updates (`show()` etc.); the
  hub publishes topics from emitted Events as a side effect of
  accepting Updates. There is currently no wire kind by which an
  external process initiates a `publish()`. If generalized
  peer-to-peer pub/sub from external publishers is later needed it
  would be additive — a `PublishMessage` wire kind that triggers
  the hub's `publish()` from outside — but it must not replace or
  compete with the typed Update channel.

### Authority

The decision is the operator's, reached through design discussion in
the post-PR-2 session that produced `docs/architecture/archive/io-model.md`.
The operator named the Observer pattern explicitly as the right
shape; this ADR records the decision so the choice doesn't get
re-proposed as polling or as point-to-point.

### Relationship to other decisions

- DES-031: this ADR introduces a SECOND inter-actor communication
  mechanism alongside the Update/Event flow DES-031 established.
  Updates/Events are inside the Lux fabric; Observer is across the
  MCP boundary.
- DES-032: this ADR doesn't change Element ownership or behavior.
  Element behavior methods emit typed Events (e.g. `ButtonClicked`)
  via `self._emit`; the hub's emit handler routes Events to
  `publish()` (Observer channel) and Updates to `accept` +
  ship-to-display (typed channel). Behavior methods do **not**
  call `hub.publish` directly — see
  `spikes/io_model_v1/ARCHITECTURE_NOTES.md` A2 for the
  typed-Events-vs-Observer-notifications distinction. Observers
  can react to notifications by composing further state changes
  via `show()` / `Display.apply(...)`.
- DES-033: this ADR's per-tier Renderer / Encoder families are
  unaffected. The MCP boundary is its own protocol surface; the
  Encoder family is for Lux IPC, not MCP.
- DES-034: this ADR sits alongside DES-034's IPC/render decoupling.
  Observer notifications are a third channel (Updates, Events,
  notifications), with notifications targeting MCP-connected
  agents.
- DES-035: this ADR's `publish` and `subscribe` mechanisms can be
  used by handlers in any of DES-035's three handler patterns —
  deterministic handlers can publish; agent-escalation handlers can
  both subscribe and publish.
- `docs/architecture/archive/io-model.md` §"Agent observers — MCP boundary" —
  the long-form spec.
- `docs/oo-refactor/migration-plan.md` PR 11 — the migration PR that
  introduces this subsystem.

## DES-037: Display Singleton Lifecycle — Socket-Authoritative Liveness, Two-Lock Discipline, Self-Arbitrating Bind

**Date:** 2026-07-04
**Status:** ACCEPTED
**Decided by:** the operator
**Companion doc:** `docs/display_lifecycle.tex` (Z spec, ProB-verified) + `docs/display_lifecycle_coverage.md`

### Problem

There must be exactly one `lux-display` process bound to a given
socket path. Multiple front doors can spawn one — a `DisplayClient`
with `auto_spawn=True` (the beads render hook fires it on every `bd`
command), `make restart`, and a human running `lux display` directly —
and any of them can run concurrently with a `reap()` or a stale-file
cleanup. The original guard (lux-w8t5's predecessor) decided liveness
from a PID **file** and unlinked the socket on a stale read; that leaked
orphaned windows across a session. Fixing it empirically took 16 review
rounds (13 on lux-w8t5, 3 on lux-h29e), each surfacing another
interleaving: recycled-PID false-alive, a live socket unlinked while its
owner was slow to handshake, a zombie read as alive, a two-winner race
where a concurrent cleanup unlinked a freshly-bound socket, a
`make restart` spawn outside the lock, a stalled display misread as dead.

The recurrence itself was the signal: this is a finite-state concurrency
problem, and empirical testing samples interleavings rather than proving
them.

### Decision

The display lifecycle is a state machine over the socket path, governed
by four architectural commitments:

1. **The socket is authoritative for both liveness and identity — never
   the PID file.** Liveness is a tri-state probe (`SocketLiveness`:
   `DEAD` / `ACCEPTING` / `READY`) that *connects* to the socket. A
   process that accepts a connection is a live owner and is never
   unlinked or spawned over, even before it completes the `ReadyMessage`
   handshake. Identity (which PID owns the socket, for reaping) is read
   from the OS peer credential of the connected socket (`LOCAL_PEERPID`
   on macOS, `SO_PEERCRED` on Linux) — not from a file that can go stale,
   be recycled, or be deleted.

2. **Two locks, acquired only in the order spawn → bind.** The
   **spawn-lock** (`<sock>.sock.lock`) is held by `ensure()`/`reap()`
   end-to-end (through `_await_ready`) to serialize spawn/reap decisions.
   The **bind-lock** (`<sock>.sock.bindlock`) is held by the display
   server's `setup()` across its `{probe, cleanup_stale, bind, listen}`
   critical section. `setup()` takes *only* the bind-lock; `ensure()`/
   `reap()` take the spawn-lock and, briefly and inner, the bind-lock for
   cleanup — releasing it before `_await_ready`. The order never inverts,
   so the two cannot deadlock.

3. **The server self-arbitrates at bind; `setup()` must not take the
   spawn-lock.** `setup()` cannot hold the spawn-lock, because `ensure()`
   holds that lock while waiting for the very display whose `setup()`
   would then block on it — a self-deadlock. Instead the OS's atomic
   `AF_UNIX` `bind()` is the mutex: `setup()` probes for a live owner
   (exits `0` if one is serving — before opening any window), clears only
   a confirmed-dead socket under the bind-lock, then `bind()`s. A lost
   race (`EADDRINUSE`/`EEXIST`) means another instance won → exit `0`; any
   other `OSError` fails loud.

4. **The design is formally specified and model-checked (see DES-038),
   not merely tested.** `docs/display_lifecycle.tex` is the source of
   truth for the invariants; the code refines it.

### Rationale

- **PID files lie; sockets don't.** A PID file can name a recycled PID
  (false-alive), be missing while the owner lives (false-dead → unlink
  the live socket), or be deleted. The kernel's socket state and peer
  credential are ground truth for "is someone serving here, and who".
- **Two locks because one cannot cover both concerns without
  deadlocking.** A single lock held from spawn through serving would
  block the spawned display's own bind. Splitting spawn-serialization
  from bind-serialization, with a fixed acquisition order, gives mutual
  exclusion where each is needed and provable deadlock-freedom.
- **Bind-as-mutex closes the last race the locks can't.** A hand-run
  `lux display` bypasses `ensure()`'s spawn-lock entirely; the atomic
  `bind()` is the one arbiter every path shares, so making the server
  self-arbitrate there (rather than trusting an external lock) covers
  the bypass.
- **`ECONNREFUSED` is ambiguous, so mitigate rather than disambiguate.**
  A backlog-saturated live socket and a dead socket both refuse
  `connect`. The probe cannot tell them apart, so the `listen()` backlog
  is large (128) to make a live-but-briefly-stalled display's queue
  effectively un-fillable at lux's client count, rather than pretending
  the probe can distinguish the two.

### Alternatives considered

- **PID-file liveness (the original).** Rejected: recycled-PID and
  stale-file false reads are the entire defect class this ADR closes.
- **A single lock covering spawn → serving.** Rejected: deadlocks the
  spawned display's bind against the spawner still holding the lock.
- **`setup()` acquires the spawn-lock.** Rejected: self-deadlock, since
  `ensure()` holds it awaiting readiness. This is the specific trap the
  bind-lock avoids.
- **Disambiguate `ECONNREFUSED` (backlog-full vs no-listener) at the
  probe.** Rejected: impossible at the socket API level; the large
  backlog is the pragmatic mitigation.
- **Keep hardening empirically (round 17+).** Rejected by the operator:
  a recurring concurrency defect warrants formalization (DES-038).

### Relationship to prior ADRs

- Sits under the Hub/Display topology (DES-030 onward): this ADR governs
  the *process lifecycle* of the display, orthogonal to the rendering,
  Update/Event, and MCP-boundary concerns of DES-031–036.
- `DisplayPaths` (display lifecycle) and `HubPaths` (luxd lifecycle,
  extracted in lux-bsrs) are the two symmetric lifecycle owners.

### References

- `src/punt_lux/paths.py` (`DisplayPaths`), `src/punt_lux/socket_server.py`
  (`SocketServer.setup`), `src/punt_lux/display/server.py` (`run()` guard).
- `docs/display_lifecycle.tex` + `docs/display_lifecycle_coverage.md`.
- Beads lux-w8t5 (liveness/reap) and lux-h29e (bind arbitration).

## DES-038: Formal Verification (Z + ProB) for Concurrency and State-Machine Defects

**Date:** 2026-07-04
**Status:** ACCEPTED
**Decided by:** the operator
**Companion doc:** `CLAUDE.md` §"Formal Verification (z-spec)"

### Problem

The display-lifecycle defect (DES-037) was chased across 16 empirical
fix/review rounds. Every round a new interleaving surfaced, was fixed,
and a test was added — yet the next round found another. Tests *sample*
the interleaving space; they cannot prove its absence of violations. A
"50/50 green" concurrency test is confidence, not proof, and a passing
test can silently exercise a stubbed premise rather than the real
mechanism (the partition audit found exactly this: the bind-window
"bound-not-listening reads dead" premise was monkeypatched, never
proven against a real socket).

### Decision

For the class of change that is **concurrency, a lock discipline, or a
safety-critical state machine** — and, as a hard rule, the moment the
**same class of defect recurs across two or more fix rounds** — the design
is **formally specified in Z and model-checked with ProB** before merge.
The model check, not a green test run, is the merge gate. Specifically:

1. `z-spec:code2model` → a Z spec of the state machine (flat state,
   bounded carrier, single `Init`).
2. `fuzz` type-check; `probcli -model_check` every safety invariant plus
   the deadlock check over a bounded carrier (setsize 2–3 exhibits the
   races).
3. **Fidelity check (mandatory):** the model must reproduce the *known*
   defect when the fix is removed (drop the lock → ProB returns the exact
   bad interleaving). A model that cannot reproduce the bug it guards is
   too abstract to trust.
4. `z-spec:partition` + `z-spec:audit` — derive the test partitions from
   the spec and fill every coverage gap; a test that stubs the mechanism
   is a gap, not coverage.
5. Commit the spec (`docs/*.tex`) as a regression artifact; re-check when
   the modeled code changes.

The full rule is codified as a standard in `CLAUDE.md`.

### Rationale

- **A finite state space is provable; testing only samples it.** The
  spawn/reap/bind/cleanup interleaving under two locks is finite and
  exhaustively checkable. Model-checking replaces N rounds of "find one
  more interleaving" with one exhaustive pass.
- **The fidelity check prevents false confidence.** A model that passes
  because it is too abstract to express the bug is worse than no model.
  Requiring it to reproduce the known counterexample makes the green
  result meaningful.
- **Formal verification and code review are complementary, not
  redundant.** ProB proves the concurrency invariants it models; it does
  not model signal-handler timing or fd cleanup on error paths. On this
  very change, Bugbot and Copilot caught a SIGTERM-teardown window and an
  fd leak that were out of the model's scope. Both layers are required.

### Alternatives considered

- **Keep hardening empirically.** Rejected — it had failed 16 times.
- **TLA+ / Alloy instead of Z + ProB.** Not adopted: the org already
  standardizes on z-spec (fuzz + probcli), and Z + ProB was sufficient to
  model the lifecycle and find/verify the races. Revisit only if a future
  problem exceeds ProB's practical model-checking capacity.
- **Model-check but skip the partition/audit coverage step.** Rejected:
  the audit is what caught the tests stubbing the mechanism; proving the
  design without proving the tests exercise it leaves a real gap.

### Relationship to prior ADRs

- The reference application of this methodology is DES-037. This ADR
  captures the *methodology* decision; DES-037 captures the *architecture*
  it verified.

### References

- `CLAUDE.md` §"Formal Verification (z-spec)"; `docs/display_lifecycle.tex`;
  `docs/display_lifecycle_coverage.md`. Toolchain: `/z-spec:setup`.

## DES-039: Self-Validating Elements — Component-Appropriate `validate()`, Collect Across the Hierarchy, Return to the Agent

**Date:** 2026-07-04
**Status:** ACCEPTED
**Decided by:** the operator
**Companion docs:** `docs/architecture/target/element-contract.md`,
`docs/architecture/target/ui-model.md`

### Problem

Elements silently accepted malformed input. A table whose rows did not
match its column count, or held an unrenderable cell (a list or dict), was
handed straight to the renderer — which drew a mis-columned table, or the
render layer faulted downstream, far from the cause. The agent that sent
the bad UI got `ack:` (success) back, indistinguishable from a correct
render, with no actionable signal and no chance to self-correct. This is a
silent-accept-invalid-input class: the same class Lux's introspection and
error machinery exist to eliminate, reappearing at the element data layer.

### Decision

Elements **self-validate**. The contract has four parts:

1. **Placement — on the component.** Each element kind implements
   `validate() -> tuple[ValidationError, ...]` returning its *own*
   component-appropriate errors. What "valid" means is decided per kind:
   a table checks rows fit the declared columns and cells are renderable
   scalars; a tree checks its nodes are well-formed mappings with labels.
   There is no universal validity rule and no central validator switch.
   The default (`Element` ABC) returns `()` — a kind with no invariant to
   fail self-validates vacuously.
2. **Trigger — `show()`, between decode and render.** After `show`
   decodes the wire tree, an `ElementTreeValidator` walk runs before the
   tree is installed/rendered. `show` is the trigger; it does not itself
   know what any element considers valid.
3. **Aggregation — collect across the hierarchy, no fail-fast.** The walk
   recurses the whole tree (via each container's `child_elements()`),
   calls every element's `validate()`, and accumulates *all* errors. The
   agent sees every problem at once, not the first.
4. **Return to the agent; never render invalid.** The collected set is
   returned in the `show` response (`error: scene not rendered — N
   validation error(s): …`, each naming the offending element's id/kind).
   An invalid tree is **not** handed to the Hub/Display — the render is
   protected, and the agent gets exactly what it needs to fix its data and
   retry.

Supporting types: `ValidationError` (frozen value class — `element_id`,
`element_kind`, `message`); `ValidationReport` (aggregate — `ok`,
`error_count`, `describe()`); `SelfValidating` and `HasChildElements`
`runtime_checkable` protocols (structural, so frozen wire dataclasses and
the `Element` ABC satisfy the same walk with no shared base). Every
child-bearing container implements `child_elements()`; a structural guard
test derives the container set from the `Element` union and fails if a new
container kind omits it — so coverage cannot silently regress.

The contract is **universal** (every kind has `validate()`) and the **logic
is component-appropriate**. The exemplar was proven on `table`, itself a
not-yet-ABC-migrated kind, to lock the contract shape on a known-good element.
Going forward `validate()` is added **as part of migrating each element** to the
new design (DES-030+ and the migration plan), not as a separate validation-only
pass over legacy kinds: a migrated element that is not self-validating is not
done, and new kinds land self-validating on the new path only after the current
kinds migrate.

### Rationale

- **Data and behavior belong together (PY-OO-5).** "What is a valid
  table" is knowledge the table owns; putting it on the table (not in a
  `show`-side switch) is the object-oriented placement and scales per kind.
- **Aggregation beats fail-fast for a non-interactive producer.** The
  agent is not in the render loop; a single round-trip that reports every
  error lets it fix the whole tree at once instead of one-error-per-retry.
- **Rejecting before render protects two processes.** The Hub and Display
  are separate processes; an invalid tree that reaches the renderer can
  fault it far from the cause. Validating at the Hub boundary keeps the
  malformation on the producer's side of the wire.
- **Prior art, synthesized.** ImGui (immediate mode) validates each
  widget's arguments *on the widget call* — component-appropriate
  placement, but fail-fast and no aggregation. Retained-mode form
  frameworks (Django `Form.full_clean`, WTForms) put validators on each
  field, then the form walks every field, aggregates all errors, and
  refuses to commit an invalid form. The decision keeps ImGui's placement
  and adopts the form frameworks' aggregation.

### Alternatives considered

- **Validate inside `show()` (a central validator).** Rejected — not
  component-appropriate, does not scale as kinds are added, and puts table
  knowledge in the tool layer instead of on the table (PY-OO-5 violation).
- **Fail-fast on the first error.** Rejected — a non-interactive agent
  should see every problem in one response to self-recover in one round.
- **Document the footgun only.** Rejected — documentation fixes neither
  the crash nor the silent-accept. Automate (reject before render) and
  validate (surface the error) first; document second.
- **Render the invalid tree and let ImGui cope.** Rejected — reintroduces
  the silent-garbage class and can crash the renderer downstream of the
  cause.
- **Per-container `child_elements()` with no structural guard.** Rejected
  during review — the "add a method to each of N containers and hope none
  are missed" shape is exactly what let four of five containers ship
  unvalidated in the first implementation round. The derivation-based guard
  test makes a forgotten container a test failure, not a silent gap.

### Relationship to prior ADRs

- Builds on the introspection primitive (`render_path`/`resolved_props`,
  bead lux-b5wy) — the same "verify the running system programmatically"
  posture, now extended so the agent verifies its *own* UI before it
  renders.
- Complements DES-021 (two-tier handler dispatch): D21 governs how
  interactions cross the Hub/Display boundary; DES-039 governs what UI is
  allowed to cross it in the first place.

### References

- `src/punt_lux/domain/validation.py`, `validation_walk.py`,
  `element_abc.py`; `src/punt_lux/protocol/elements/table.py`,
  `layout.py`; `src/punt_lux/tools/tools.py` (`show`).
- Tests: `tests/domain/test_validation.py`, `test_validation_walk.py`,
  `tests/test_table_validation.py`, `tests/protocol/test_layout_containers.py`,
  `tests/test_tools.py`.

## DES-040: Interaction Model and Tool/Skill Surface — View Logic vs Business Logic, `show` as the Universal API, Widgets as Skills

**Date:** 2026-07-04
**Status:** ACCEPTED (design direction; implementation downstream)
**Decided by:** the operator
**Companion docs:** `docs/architecture/target/ui-model.md`,
`docs/architecture/target/introspection-api.md`

### Problem

Two related design questions surfaced alongside self-validation and were
settled by the operator; capturing them here prevents re-litigation.

1. **Interactions have two halves that Lux conflates.** A dialog's
   "dismiss on OK" is *view logic* (built into the widget); "what OK
   *does*" (delete a ticket, save a form) is *business logic* that only
   the agent knows. Today an interactive element with no wired business
   handler (a dialog button with no `click` verb; a handler-less button)
   is silently inert and still returns `ack:` — a second instance of the
   silent-accept class.
2. **The MCP tool surface does not scale by adding a tool per widget.**
   `show_table` / `show_dashboard` are data schemas that ultimately
   `return show(...)`; a tool per widget makes every agent carry the
   complexity of every widget.

### Decision

- **View logic is built-in and may be automatic; business logic is
  agent-wired.** A dialog's dismiss/confirmed/cancelled state is view
  logic the widget owns. The consequence of a click is wired
  out-of-band by the agent (publish a topic → the agent `recv`s it, or a
  Hub-side handler). The `OK → confirm` auto-mapping covers only the view
  half. Rationale via the ImGui lens: immediate mode colocates click and
  consequence because the application is in the loop; Lux's agent is *not*
  in the loop (it sends JSON), so the consequence is necessarily wired
  separately.
- **A silently-inert interactive element is a defect, to be closed by
  automate + validate, not documentation.** Auto-wire the view half where
  unambiguous; self-validation (DES-039, extended to interactive kinds)
  surfaces missing business wiring as a validation error rather than a
  dead control that reports success.
- **`show` is the one universal render API.** It takes an arbitrary
  element tree. `show_table` / `show_dashboard` are thin data-shaping
  conveniences over `show`; the direction is to express widget
  conveniences as **skills** (opt-in, low-consequence, composed from
  `show`) rather than as standing MCP tools (every tool is complexity
  every agent carries). "The elements are limited; the ways they combine
  are unlimited" — the tool surface should reflect that.
- **`register_tool` → `register_action`.** The call registers a menu
  action that calls back to the agent (via `recv`); "tool" collided with
  both MCP-tool and the on-screen "Tools" menu. The name changes to
  `register_action`.
- **No migration shims.** Lux's users are internal only; renamed or
  retired surfaces change directly (PL-PP-1), with no compatibility
  aliases.

### Rationale

- The view/business split is the honest consequence of the agent being
  out of the render loop; naming it prevents the recurring instinct to
  "just make OK do the thing" inside the display.
- A universal `show` plus skills keeps the MCP contract small and stable
  while letting convenience grow without taxing every agent — the same
  closed-core / open-composition posture the architecture favors
  elsewhere.

### Alternatives considered

- **A tool per widget.** Rejected — does not scale; grows the MCP surface
  every agent carries for conveniences most calls never use.
- **Auto-wire business logic too.** Rejected — the display cannot know what
  OK *means*; guessing would produce confident-but-wrong side effects.
- **Document the inert-control footgun instead of validating it.**
  Rejected for the same reason as DES-039's documentation alternative.

### Relationship to prior ADRs

- Extends DES-039: the same self-validation mechanism that rejects
  malformed *data* is the mechanism that will surface missing interaction
  *wiring*.
- Refines DES-021 (two-tier dispatch) and DES-036 (observer at the MCP
  boundary) on the producer-facing side — how agents *describe*
  interactions and menu actions, not how the Hub dispatches them.

### References

- `src/punt_lux/tools/tools.py`, `tools/subscribe_tools.py`,
  `tools/server.py`; `docs/architecture/skill-tool-reusability-audit.md`
  (the audit that scoped this); `docs/architecture/target/ui-model.md`.

## DES-041: Migration Strategy — Fork, Don't Mix; Order by Testability

**Date:** 2026-07-05
**Status:** ACCEPTED
**Decided by:** the operator
**Companion doc:** `docs/architecture/migration/README.md`
**Supersedes:** the "incremental crossing, big-bang deletion" migration
decision (prior `migration/README.md` §"Ratified design decisions" #2).

### Problem

The prior migration approach crossed element kinds onto the Element-ABC /
Hub-Display path one family at a time while keeping the legacy render/dispatch
path alive for everything not yet crossed (the pump's mixed-scene skip). That
coexistence window is the cost: every migration had to navigate the seam
between the two paths, and **mixed composites** — an ABC element inside a
legacy dataclass container, and the reverse — required factory-rebind walks
through legacy containers, mixed-scene routing, and wiring ABC handler closures
across the legacy container's JSON leg, which cannot be made to work cleanly.
The DI-truth review (PR #237) surfaced a latent first-frame crash from exactly
this mix. Servicing the mix is friction on every element, indefinitely.

### Decision

Stop servicing the mix; eliminate it.

1. **Fork, don't mix.** Build the new ABC path as a parallel track. Do not
   invest in making legacy and ABC elements interoperate inside composites.
2. **Duplicate only on need.** When both a legacy and a new version of one
   element must exist short-term, the **new ABC class takes the canonical
   (real) name and the legacy class is renamed out of the way**. Do not
   duplicate unless something forces it.
3. **Order by testability, bottom-up.** Testing is our choice, so the order
   optimizes for what makes the system composable and testable soonest:
   migrate a **container** ("a frame") and element **primitives** first, so
   real layouts can be composed and tested, then build up to more complete
   widgets. Complex widgets (`table`, `plot`, `draw`) come **last**.
4. **One element (and 1–2 containers) at a time.** Each migrated kind is an
   Element-ABC subclass that paints via `Element.render()` and self-validates
   (`validate()`, DES-039).

### Consequence

The mix problems dissolve by construction. Because a container is migrated
early and composites are built all-ABC, a new element is never nested inside a
legacy container (and where a scene would force it, the element is duplicated
instead). So the C3 limitation (don't nest an ABC element in a legacy
container, `abc-baseline-debt-audit.md`) is **avoided, not fixed**, and the
coexistence machinery — factory-rebind walks through legacy containers,
mixed-scene routing, ABC-handler wiring across the legacy JSON leg — is **not
built**.

### Rationale

- **A fork avoids a long, friction-heavy coexistence period.** Two parallel
  representations short-term are cheaper than a bridge between two incompatible
  ones.
- **Bottom-up buys testability immediately.** A frame plus primitives let us
  compose and drive real UI through the introspection + interaction surface
  from the first migration; a complex widget migrated early buys nothing
  testable and costs the most.
- **Duplicating an element is cheap; bridging is not.** A renamed legacy class
  beside a canonical ABC class is a mechanical, reversible state that the
  migration retires as each kind crosses.

### Alternatives considered

- **Incremental crossing with mixed-scene coexistence** (the prior decision).
  Superseded — it pays the mixed-state tax on every element and produced a
  latent crash class.
- **Full big-bang** (convert all 25 kinds at once). Not adopted — too large a
  single change to review and verify; the bottom-up fork reaches the same clean
  end state incrementally and testably.
- **Batch-by-risk sequencing** (the prior 7-batch order). Superseded by
  testability-order (containers + primitives first, `table`/`plot`/`draw`
  last).

### Relationship to prior ADRs

- The render-path unification (the Template Method `Element.render()` engine +
  per-kind adapters) is the **fork's render engine** and the prerequisite for
  migrating any kind onto the new path (see
  `docs/architecture/migration/render-path-unification-design.md`).
- DES-039 stands: `validate()` rides with each element's migration.
- The Element-ABC contract (DES-030+) and the "one `ElementABC` for everything"
  decision are unchanged; only the *coexistence and sequencing* strategy is
  replaced.

### References

- `docs/architecture/migration/README.md` (the plan, reconciled to this ADR),
  `render-path-unification-design.md`, `abc-baseline-debt-audit.md` (C3).

## DES-042: The Render Engine — `Element.render()` Is the Paint Path (Template Method + Per-Kind Adapters)

**Date:** 2026-07-05
**Status:** ACCEPTED
**Decided by:** the operator
**Companion doc:** `docs/architecture/migration/render-path-unification-design.md`
**Implemented:** PR #239 (built on the DI-truth fix, PR #237)

### Problem

Before this decision, "a kind is on the ABC path" meant only that its *type*,
codec routing, and `HubDisplay` installation had flipped — the live pixels
still flowed through the legacy `ElementRenderer`. Only `text` actually painted
through `Element.render()`; `button`/`checkbox`/`dialog` were ABC in type but
still painted via the legacy per-kind dispatch, because the ImGui factory had
no adapter for them. So `render_path == "abc"` (the introspection signal)
misrepresented reality, and no kind could be migrated *and painted* through the
new path. `Element.render()` also hardcoded a leaf-vs-composite branch in the
base class, so no component could vary a single render step.

### Decision

Make `Element.render()` the real paint path for every ABC kind.

1. **A fixed Template-Method skeleton, never overridden.** `render()` runs the
   steps in order — `opened = _begin(r); if opened: _paint_self(r);
   _render_children(r); _end(r, opened)` — and calls four overridable step
   hooks, **each with a default that delegates to the renderer** (`_begin` →
   `renderer.begin()`, `_paint_self` → `renderer.paint()`, `_render_children` →
   recurse `_children()`, `_end` → `renderer.end(opened=...)`). A leaf or plain
   box overrides nothing; a component overrides only the steps it needs (a
   `dialog` overrides `begin`/`end` for its modal + dismiss; a `group`'s layout
   lives entirely in its renderer's begin/end).
2. **Per-kind ImGui adapters** resolved through the factory (`(type → adapter)`
   dispatch table) reuse the existing per-kind paint logic verbatim; the DI
   factory is rebound onto received ABC elements (`bind_renderer_factory`,
   PR #237) so `render()` resolves a real renderer, not the sentinel.
3. **`_paint_element` flips** top-level ABC elements to `elem.render()`.
4. **The legacy-dispatch prune is DEFERRED to fork completion.** During the
   mixed period an ABC leaf nested in a legacy container still paints via the
   retained legacy per-kind renderer; the prune (retiring the legacy path)
   lands only when no legacy container can hold an ABC child. `render()` wraps
   its inner steps in `try/finally` so a raising child can never leave an ImGui
   surface unbalanced.

After this, `render_path == "abc"` means the element **paints** via the new
path, and migrating a kind is: ABC subclass + `validate()` + an adapter.

### Consequence

Any migrated kind paints through `render()` via its adapter; composites recurse
their children through the default `_render_children`; the "abc ≠ paints" gap
the migration README warned about is closed. Replication stays whole-UI resend
(no diff protocol) — UI state crosses IPC, render calls do not (target.md).

### Rationale

Composite + Template-Method: a leaf is a degenerate container, and every
component varies steps of one fixed algorithm instead of the base class
deciding for it (open-closed). A `dialog` is an ordinary component, not a
special case.

### Alternatives considered

- **Keep the `isinstance`-per-kind `_paint_element` switch.** Rejected — it
  grows a branch per migrated kind and inverts the domain→protocol dependency.
- **A diff/incremental replication protocol.** Not adopted — whole-UI resend on
  change is simpler to inspect and reason about (target.md); a diff protocol is
  deferred until a real performance problem appears.

### References

- `render-path-unification-design.md`, PR #239, PR #237 (DI-truth).

## DES-043: Patch-Application Crash-Freedom — No Agent Input Terminates the Display

**Date:** 2026-07-05
**Status:** ACCEPTED
**Decided by:** the operator
**Companion doc:** `docs/patch_application.tex` (regression artifact)
**Applies:** DES-038 (formal verification for state-machine defects)
**Implemented:** PR #241

### Problem

Migrating `progress` — the first kind with a value-*range* invariant
(`fraction ∈ [0,1]`) — exposed that the display-side patch path did not survive
a bad agent patch. A rejected setter's exception propagated out of
`SceneManager.apply_update` to the display message loop and **terminated the
display process** — one bad `update()` killed the window. The same class
recurred across **four** rounds (out-of-range `ValueError`, `TypeError`,
non-atomic partial mutation, unknown-field/structural error); empirical
case-by-case patching kept missing cases, and one hand-written partition test
even asserted the crash as the correct contract. Separately, the display-side
state machine reached elements via a concrete-`isinstance` ladder that never
learned the ABC kinds, so patches to an element nested in an all-ABC `group`
were **silently dropped** and its stale ids were missed on scene replace.

### Decision

1. **Crash-freedom is a system invariant.** No agent patch of any kind may
   terminate the display message loop.
2. **The state machine reaches ABC subtrees via the `child_elements()`
   Protocol**, not a concrete-`isinstance` ladder — extracted `SceneTreeWalk`
   (navigation) and `PatchApplier` (per-patch application). An ABC element
   patches in place via `apply_patch`; a legacy element via `replace` + list
   rebind; every legacy container kind is covered (a structural test asserts it,
   so a new container cannot silently reintroduce the gap).
3. **A rejected patch is caught per-patch, logged, and skipped.** A validated
   setter rejects a bad value by raising; `PatchApplier` catches the rejection
   (value *and* structural) inside the batch loop, logs it, and continues. The
   catch is **per-patch, not batch-level** — batch-level would satisfy
   crash-freedom but violate **batch-continuation** (a later valid patch must
   still apply). `Element.apply_patch` snapshots and rolls back on any setter
   exception, so a rejected patch is **atomic** (no field partially mutated).
4. **A loop-level boundary backstop** at the display message handler
   (`except Exception`, log + continue — the PY-EH-6 system-boundary guard)
   contains any escape outside the expected rejection classes.
5. **Formalized per DES-038.** `docs/patch_application.tex` is fuzz-clean and
   ProB-model-checked: crash-freedom, atomicity, validity-preservation, and
   batch-continuation all hold exhaustively (4445 states), deadlock-free, and
   the fidelity variants reproduce all four defects when a guard is removed.
   Committed as a regression artifact — re-run `fuzz` + the model-check whenever
   the modeled code changes.

### Consequence

No agent input can crash the display. The four-round recurrence is closed with
a proof over the whole bounded state space, not another empirical fix. The model
also showed rounds 1 and 2 were one case class (two `except` clauses patched
separately) — evidence that empirical enumeration doubled the work.

### Rationale

Crash-freedom is a state-space property: model-checking proves it, testing
samples it. The recurrence signal (the same defect class across ≥ 2 rounds) is
exactly DES-038's trigger to formalize; it was applied late (round 4), and the
lesson — formalize on the second repeat, not the fourth — is recorded.

### Alternatives considered

- **Continue empirical case-by-case fixing.** Rejected — it missed cases across
  four rounds and encoded a crash as a passing test's contract.
- **A single batch-level `try/except` around `apply_update`.** Rejected —
  satisfies crash-freedom but aborts the remaining patches in the batch,
  violating batch-continuation (the model exhibits this trace).

### References

- `docs/patch_application.tex`, DES-038, DES-039, PR #241.

## DES-044: End-to-End Business-Event-Loop Harness — In-Process, Boundary-Faithful Verification

**Date:** 2026-07-06
**Status:** ACCEPTED
**Decided by:** the operator
**Companion doc:** `docs/architecture/e2e-harness-design.md`
**Implemented:** PR #243

### Problem

Each migrated element is unit-tested for render, validate, and fire in
isolation, but the full io-model loop — a UI interaction crossing to the Hub,
running the real handler once on the authoritative copy, publishing a business
event a subscriber receives, the agent reacting by pushing a change back, and
the Hub re-pushing a replica the Display reflects — had **never been verified
end-to-end on a composed surface**. The strongest prior "e2e" test
(`test_dialog_interaction_trace.py`) drives the **test-only** `Display.interact`
— whose own docstring states that under D21 the display forwards interactions to
the Hub and production interaction dispatch runs on the Hub side, so `interact`
is the in-process dispatch contract, not the production path — so it never
exercised the real Hub path. That is the *illusion of progress* — green tests certifying a loop
nobody has run across the real boundary.

### Decision

Build a standing gate (`tests/e2e/`) that proves the full bidirectional loop
across the real boundary, for composed migrated surfaces.

1. **In-process, no socket / subprocess / GPU.** Wire the Hub and a windowless
   **production** `DisplayServer` over `InMemoryConnection` — the SAME
   `Connection` interface `LineSocket` implements — so the boundary is crossed
   through the real abstraction, not around it. A faithful boundary, not a stub.
2. **No-stub invariant.** The interaction lands in the production
   `ClientRegistry._hub_interaction_dispatch` on the authoritative `HubDisplay`,
   fired exactly once; handlers, `hub.publish`, and the inbox run for real. A
   `RaisingRendererFactory` binds every replica element so an accidental
   `render()` **raises** — "no pixels in this loop" is a *proven* property.
3. **Inject at our own event layer.** Injection fires the replica's own wrapped
   `Element.fire` — the exact call the button renderer makes on a real click —
   so the crossed `RemoteEventHandlerInvocation` is byte-identical *by
   construction*. No test-facing Display method, no wire control message; **zero
   `src/` changes**.
4. **Agent-driven and bidirectional.** A simulated agent drives the whole
   circle, including the **return path**: it reacts to the delivered business
   event by pushing a change back, and the re-pushed replica reflects it. The
   react is gated on delivery (no delivery ⇒ no react), so the causal chain is
   asserted, not assumed.
5. **Data-driven `Scenario` framework.** Adding a migrated kind is one
   `Scenario` value; extensibility is proven with `button`, `checkbox`,
   `dialog`, and `payload` scenarios, plus the five deny-paths, connection
   isolation, and a container-exposes-children guard.

### Consequence

"Migrated" can now mean "its interaction+business-event loop is green in the
harness", not just "it renders". An interactive kind is Level-4 (per
`tests/CLAUDE.md`) when it has a passing `Scenario`. `djb` confirmed the boundary
is genuinely unstubbed.

### Alternatives considered

- **A GPU-gated visual layer / headless display peer (L1/L2 split).** The
  original design. Superseded — the loop is *messages, not pixels*; the pixel
  paint and the proof that a real GLFW click emits the same wire event as the
  injection are **deferred** with the screenshot layer (DES-028).
- **A test-only `InjectInteraction` wire control message, or a `--test-click`
  startup flag.** Rejected — generating the same event at our own layer (fire
  the wrapped handler) is strictly more faithful and needs no `src` change or
  protocol addition.
- **Subprocess + real Unix socket (extend `test_e2e.py`).** Rejected for the
  standing gate — in-process DI over `InMemoryConnection` crosses the same
  `Connection` boundary without the socket/GPU/subprocess cost and is
  CI-capable.

### Deferred (each tracked)

- **CI wiring** — the gate is CI-*capable* but the `integration` tier is
  excluded from CI (`-m 'not integration'`); land now, wire CI as fast-follow
  (`lux-lodl`, with `lux-gqai` to stabilize the real-subprocess tests it
  enables).
- **Framing-switch** — the harness rides the target `Connection` interface;
  production `DisplayClient`/`SocketServer` still use bespoke framing
  (`lux-5zhw`). Until the flip, the harness proves the loop *logic* over a
  byte-faithful abstraction, not today's exact production wire bytes.
- **Pixel / injection-fidelity** — the real GLFW paint and the real-click ==
  injection wire-equality proof, deferred with DES-028 (screenshot).
- **Interaction dedup / anti-replay** — the dispatch has no dedup; a replayed
  frame double-fires. The harness documents this honestly (single-fire *per
  injection*, not replay resistance) rather than claiming a defense the system
  lacks; whether one is warranted is `lux-x8rb`.

### References

- `docs/architecture/e2e-harness-design.md`, PR #243, `tests/CLAUDE.md`
  (Level 3–5 gate), DES-028; beads `lux-lodl`, `lux-gqai`, `lux-5zhw`,
  `lux-x8rb`.

## DES-045: Sub-Element Addressing — Stable ID, Never a Positional Index

**Status:** accepted. Cross-cutting invariant for every composite element.

Element-level identity and routing are already settled and uniform. Every
element — a scene root or a nested child — has a **stable, scene-scoped,
agent-provided `id`** (`element-contract.md`, "a stable `id` within its enclosing
scene"). Interaction routing is by `(scene_id, element_id)`: a
`RemoteEventHandlerInvocation` carries the pair, the Hub resolves the target
through `ElementIndex` (`(scene_id, element_id) → Element`), and `ChildIndex`
records parent→child edges so *every* element, however deep, is addressable.
Identity is decided once, at the element grain.

Addressing a **sub-part of a composite that is not itself an element** — a tab in
a `tab_bar`, a row in a `table` — had **no contract**, and had already diverged:
the legacy `table` addresses rows by positional `row_index`
(`table_renderer.py:165`), while the `tab_bar` migration was about to choose
id-vs-index independently. Identity was being re-litigated per composite.

### Decision

Every addressable sub-part of a composite is identified by a **stable id** —
agent-provided, or synthesized as a stable key — and **never by a positional
index**. Selection state and routing reference that id. A sub-part's identity is
stable under insert, remove, and reorder of its siblings. This is the element
identity principle applied one level down; it is decided **once**, here, not per
element.

### Rejected alternatives

- **Positional index** (the legacy `table` `row_index`). Fragile — a sub-part's
  index silently mis-points after any insert or reorder, so a whole-UI re-push
  that reorders siblings moves the selection to the wrong item; and it re-invents
  addressing per composite. This is the anti-pattern the ADR removes.
- **Promote every sub-part to a first-class `Element`.** A tab *could* be an
  element with its own `id`, dissolving the question — but this does not
  generalize to *data-driven* sub-parts: a `table` with 10 000 rows must not mint
  10 000 elements. The stable-id invariant covers authored sub-parts (tabs) and
  data sub-parts (rows) alike; element-promotion covers only the former.

### Consequences

- **`tab_bar`** (`lux-4n5n`): each tab carries a stable `tab_id`; the
  Hub-authoritative active-tab (see `simple-composites-design.md`) references the
  `tab_id`, and reconciliation on structural change is a membership check (added
  tab → selection unchanged; removed active tab → reset to a live tab; relabel →
  stable). This resolves the per-element "tab_id vs index" question by the
  contract, not by the kind.
- **`table`** (`lux-i3ag`, B6): row selection references a stable `row_id` — an
  agent-designated key column or a synthesized stable key — replacing the legacy
  `row_index`, fixing the latent reorder bug in the same move.
- **Every future composite** inherits the invariant; sub-part addressing is not
  re-decided per element.

### References

- `element-contract.md` (the normative sub-element addressing clause added with
  this ADR), `simple-composites-design.md` (the `tab_bar` application and the
  Hub-authoritative view-state decision), `table_renderer.py:165` (the legacy
  `row_index` anti-pattern), `domain/hub/element_index.py` /
  `domain/hub/child_index.py` (the element-level routing this extends); beads
  `lux-4n5n`, `lux-i3ag`.

## DES-046: View-State Locality — Discrete Agent-Drivable Selections Are Hub-Authoritative; Continuous In-Progress Input Is Display-Local

**Status:** accepted. Cross-cutting; determines which UI state crosses the
Hub/Display boundary and is therefore addressable (see DES-045).

The Hub (`HubDisplay`) is the authoritative store; the Display is a replica for
rendering and input capture. But some UI state is transient *view* state — which
tab is active, whether a section is expanded, the scroll offset, the text a user
is mid-typing into a filter, a window's drag position. For each such piece:
does it live **Hub-authoritative** (it crosses the wire, the Hub owns it, the
agent can read and drive it, it is re-pushed and reconciled) or **Display-local**
(the Display owns it, it never re-pushes, a whole-UI resend never clobbers it)?

Getting the line wrong fails in one of two directions. If *everything* is
Display-local, the Hub is blind to state an agent needs — it cannot switch a tab
or expand a section for the user, and the Hub/Display views silently diverge. If
*everything* is Hub-authoritative, every scroll and keystroke round-trips to the
Hub, and an unrelated whole-UI re-push clobbers the user's in-progress gesture
(snapping them back to tab 1, re-collapsing a section, resetting a half-typed
filter). `table` (DES-018/019/024) drew a first line; `tab_bar`/`collapsing_header`
(`lux-4n5n`) forced the general rule.

### Decision

The line is drawn by **kind of state**, not by widget:

- **Discrete, agent-drivable selections are Hub-authoritative.** A `tab_bar`'s
  active tab, a `collapsing_header`'s open/collapsed flag, a paged `group`'s page
  index, a `table`'s row selection. These cross the wire, the Hub owns them, the
  agent can drive them (a re-push with a new value moves the Display), a user
  gesture fires an event the Hub records, and the Hub reconciles the value when
  the structure changes. Each such selection references a stable id, never a
  positional index (DES-045).
- **Continuous, in-progress input is Display-local.** Scroll offset, the text a
  user is mid-typing into a filter, window-drag position. The Display owns it, it
  never re-pushes, so an unrelated whole-UI resend never interrupts the gesture.

### Rationale

- **Agent-drive.** Only Hub-authoritative lets the agent navigate for the user
  (switch a tab, expand a section) — the v2 "interact with my agent through the
  GUI" direction. Display-local state is unreadable and undrivable by the Hub.
- **Single source of truth and structural-change coherence.** The Hub reconciles
  a selection deliberately when the structure changes (an active tab removed →
  reset to a live tab), instead of leaving it to ImGui's implicit and surprising
  fallback.
- **The "re-push snaps to tab 1" fear was wrong.** A faithful Hub re-pushes the
  *correct* active selection, because it owns and records the user's last
  gesture. The snap-back only happens under a *stale* re-push, which authority
  prevents. This corrected an earlier draft that recommended Display-local on
  that mistaken ground.

### Rejected alternatives

- **All view-state Display-local.** Rejected — the Hub cannot read or drive
  discrete navigation; agent-driven UX is impossible and the tiers diverge.
- **All view-state Hub-authoritative.** Rejected — round-trips every scroll event
  and keystroke, and a whole-UI resend clobbers in-progress continuous input. The
  discrete/continuous split takes responsiveness for continuous input and
  authority for discrete selections.

### Consequences

- Kinds whose selection is Hub-authoritative become **interactive** — the full
  two-tier D21 path (a `RemoteDispatchSpec`, an event such as `tab_changed` /
  `header_toggled`, Hub re-dispatch, a re-push). `tab_bar` and
  `collapsing_header` are therefore interactive, not display-only.
- Hub-authoritative view-navigation **round-trips to the Hub**. Negligible for a
  local Hub; on a *remote* Hub/Display it adds a network hop before the selection
  visually changes — a deferred v2-remote optimization (optimistic local render
  with Hub confirmation), not a v1 concern.
- Every Hub-authoritative selection needs a **stable identity** to be addressable
  across re-pushes — the direct reason DES-045 exists.
- **Follow-up:** the paged-`group` page index, earlier ruled Display-local
  (`group-element-design.md`), moves to Hub-authoritative to match this rule.

### References

- `simple-composites-design.md` (the `tab_bar`/`collapsing_header` application),
  DES-045 (the identity a Hub-authoritative selection requires), DES-018 /
  DES-019 / DES-024 (table filtering, detail, and row-select — filter/scroll
  Display-local, row selection Hub-authoritative), `element-contract.md` (the
  Display is a replica, not a second authority), `group-element-design.md` (the
  paged page-index follow-up); beads `lux-4n5n`, `lux-i3ag`.

## DES-047: Hub-Authoritative Write Path — One Contract, One Seam, Legacy by Value-Replacement

**Status:** accepted (design-first; ratified with amendments). Full design in
[`docs/architecture/migration/hub-write-path-design.md`](docs/architecture/migration/hub-write-path-design.md).

A *write* mutates authoritative UI state — patch one field, remove an element and
its subtree, or clear a client's scene. Install (`show`) and interaction dispatch
(D21) already honor Hub authority; the write leg is the third. The store gate for
*field mutation* was asymmetric: an in-place patch lands on an Element-ABC object
but was refused against a frozen legacy wire dataclass, and — separately — the
MCP `update`/`clear` tools patched the Display directly, leaving the authoritative
`HubDisplay` stale so the next re-push reverted the change. This ADR settles how
mutation stays Hub-authoritative for **both** element models, mid-migration,
without a fork that must be unwound.

### Decision

- **One model-agnostic write contract.** Operations are the typed `Update`
  vocabulary (`SetProperty` / `RemoveElement` / `AddElement`), id-addressed, never
  positional, **absolute** (carry the new value, not a delta), and **idempotent**.
  Every write is an authoritative operation on `HubDisplay`; the Display learns of
  it only through the same whole-root re-push it already consumes. Never
  Display-direct.
- **Invariants.** Atomicity — a batch commits entirely or changes nothing
  (stage-validate-then-commit-or-restore, a batch-level generalization of
  `apply_patch`'s snapshot). Single authoritative mutation with an idempotent
  re-push (mutation runs once, *outside* transport retry). Ownership — a write to
  an un-owned element is rejected before any mutation; unknown ≠ not-owner.
  Validation parity with `show` (the same hierarchy walk). Hub/Display consistency
  with per-connection-scoped clear. **`id` and `kind` are immutable; unknown
  fields are rejected** — uniformly for both models. Id-keyed display-side
  transient state (selection, scroll, in-progress text) must survive a whole-root
  re-push.
- **Coexistence at one `isinstance(AbcElement)` seam.** An ABC element is patched
  **in place** (`apply_patch`), preserving object identity, handlers, and
  observers. A legacy element is realized by **`dataclasses.replace()`** on the
  frozen instance — sharing untouched fields/children by reference and overriding
  the addressed field. The seam introduces no legacy-specific method; at
  migration's end the legacy branch has zero inputs and is **deleted, not
  unwound** (the deletion-vs-unwinding test).
- **No mixed composites** (the migration simplification). A composite is
  homogeneous — all-ABC or all-legacy — enforced by the all-ABC gate and
  legacy-forcing (DES-041). This makes `replace()` on a legacy subtree
  unconditionally lossless and dissolves the only genuinely hard case (a stateful
  ABC leaf inside a legacy composite cannot exist).
- **Nested-legacy defers to `show`.** A field-patch or removal of a legacy element
  *below* a legacy composite is rejected fail-loud with a pointer to `show` (the
  always-correct whole-UI resend) — a pure simplicity choice (no spine-rebuild),
  self-deleting as the container kind migrates.

### Rejected alternatives

- **`to_dict → from_dict` codec round-trip for legacy replacement.** Strictly
  worse than `replace()`: re-decoding a legacy composite would re-decode its
  children and, absent the no-mixed-composites rule, drop a nested control's
  handler chain; even with it, it is a needless full serialize/deserialize when
  `replace()` shares by reference.
- **Retrofit `apply_patch`/setters onto legacy, or unfreeze them.** Brings the ABC
  write surface onto legacy classes ahead of migration — a bridge that is ripped
  out when the kind migrates. Mutation rides *with* each kind's migration.
- **`LegacyElementAdapter`, a field-level diff protocol, always-re-decode,
  always-in-place, splice-preserving spine-rebuild, and supporting mixed
  composites** — each is transient machinery or reintroduces Display-side
  authority. Rejected; see the design doc §7.

### Process note

This ADR was produced **design-first** (design mission → review → ratification)
after correcting an initial error in which the write path was dispatched as a
prescriptive implementation. The prescriptive impl's Hub-routing + hardening
(atomicity, retry-once, ownership, dead-`UpdateMessage` removal) is retained as
the pipeline the ratified legacy `replace()` seam builds on.

### References

- [`docs/architecture/migration/hub-write-path-design.md`](docs/architecture/migration/hub-write-path-design.md)
  (full design; author gvr, review rmh, ratified with amendments A1/A3/A4/A5/A6 +
  no-mixed-composites), `target.md` (Hub authority, replication policy),
  `element-contract.md` (validation contract, sub-element addressing),
  `domain/hub/hub_display.py` / `element_index.py` (the authoritative store this
  writes through); bead `lux-4n5n`.

## DES-048: Commit-on-Idle Reconciliation — the Mechanism for Display-Local Continuous Input

**Status:** accepted. The concrete mechanism implementing DES-046's
"continuous, in-progress input is Display-local" for the non-atomic mutable
kinds (`input_text`, `slider`, `color_picker`, `input_number`). Model:
[`docs/commit_on_idle_reconciliation.tex`](docs/commit_on_idle_reconciliation.tex)
(ProB-verified).

DES-046 draws the line — continuous input is Display-local so a whole-UI resend
never interrupts a gesture — but does not say *how* the Display holds an
in-progress edit while still honoring an agent's drive of the same field. A
non-atomic edit (typing a filter, dragging a slider, painting a color) passes
through many intermediate states before it settles, and the agent (Hub) may
re-push a new authoritative value *during* the edit. The naive handling loses in
two directions: honor every Hub re-push and the user's half-typed value is
clobbered mid-keystroke; ignore the Hub and the agent can never drive the field.
Worse, a pipelined edit — commit, then re-focus before the commit's echo returns
from the Hub — reads a stale base and silently drops the second edit. Empirical
patching chased that clobber across many review rounds before it was
model-checked.

### Decision

A per-element **arbiter** mediates every frame between the Hub value and the
Display-local edit buffer, on four id-keyed slots (buffer, editing flag,
committed value, commit-time-Hub value):

- **Idle** (no active edit) → honor the Hub value.
- **Editing** (`is_item_active`) → the local buffer wins; the Hub value is
  *deferred*, not applied — a mid-drag re-push cannot clobber the gesture. No
  per-keystroke event fires.
- **Commit** (`is_item_deactivated_after_edit`) → fire exactly **one**
  `ValueChanged`, and record the committed value plus the Hub value at commit
  time.
- **Optimistic-echo retention** → after commit, keep returning the committed
  value while `hub_value == commit_time_hub` (through the echo-latency window),
  so a re-focus during that window edits from the committed value, not a stale
  base. The window closes by **value equality alone** the instant the Hub moves
  off the commit-time marker — no echo token, no version counter.

### Rationale

- **No clobber, no spam, no lost pipelined edit** — the three failure modes
  above are eliminated by construction, not by patching.
- **Value equality is sufficient.** JSON round-trips the carrier exactly, so a
  bit-identical stored copy compares equal; the only precondition is
  reflexivity (`x == x`), which fails only for a NaN carrier — discharged at the
  `validate()` boundary (DES-039). This retired an earlier echo-token/version
  design as unnecessary machinery.
- **Model-checked, not sampled.** The five invariants (never-lost,
  editing-implies-not-yet-edited, never-clobbered, fires-at-most-once, and
  deadlock-freedom) are proven exhaustively over a bounded carrier; the z-spec
  *falsified* the obvious "defer-on-first-edit" refocus fix, which still loses a
  commit via type-before-echo. This is the recurrence rule from CLAUDE.md
  applied: the second occurrence of the defect class was formalized, not
  re-patched.

### Rejected alternatives

- **Last-write-wins (honor every Hub re-push).** Rejected — clobbers the live
  gesture; the exact failure DES-046 forbids.
- **Fire per keystroke / per drag frame.** Rejected — event spam, and the Hub
  reconciles intermediate states that were never intended as commits.
- **Echo token / version counter to detect the in-flight commit.** Rejected —
  value equality over an exactly-round-tripping carrier already closes the echo
  window; a token is machinery for a problem that does not exist once the
  carrier round-trips.

### Consequences

- Every non-atomic mutable kind is **interactive** (a `ValueChanged` on commit,
  Hub re-dispatch) and carries the arbiter in its renderer.
- The carrier must round-trip through JSON exactly and be reflexive under `==`;
  `validate()` rejects NaN for the float carrier and hex structurally forbids it
  for color.
- The mechanism generalizes across carriers — the direct basis for DES-049
  (one arbiter, many value types).

### References

- [`docs/commit_on_idle_reconciliation.tex`](docs/commit_on_idle_reconciliation.tex)
  (the ProB-verified model + partition coverage), DES-046 (the locality
  principle this implements), DES-039 (the `validate()` boundary that discharges
  the NaN precondition); `docs/architecture/migration/slider-element-design.md`,
  `color-picker-element-design.md`; beads `lux-ociy`, `lux-2qay`, `lux-5nn0`.

## DES-049: The Shared `ContinuousEditArbiter` — One Verified Reconciler Behind a Value-Accessor Seam

**Status:** accepted. Extracted once three carriers existed (rule of three).
Design:
[`docs/architecture/migration/continuous-edit-extraction-design.md`](docs/architecture/migration/continuous-edit-extraction-design.md).

The DES-048 mechanism was first shipped three times as bespoke arbiters —
`InputTextArbiter` (str), `SliderArbiter` (float), `ColorPickerArbiter` (RGBA
tuple). Their honor/defer/commit/optimistic-echo control flow is *byte-identical*;
they differ only in the carrier type and the two lines that touch it. The
question was when and how to unify them without a premature or wrong-shaped
abstraction.

### Decision

- **General solution, or not at all — and not before three.** Do not abstract
  from one or two cases (the seam would be guessed and likely wrong). Build the
  concrete arbiters until three exist, then extract the general reconciler
  **empirically** — diff the three, and let the seam be exactly what the diff
  shows, no more.
- **One `ContinuousEditArbiter[T]`** (PEP-695 generic, `@final`) holds the four
  slots and the byte-identical control flow, delegating the only two
  carrier-typed touches to an injected **`ValueAccessor[T]`** — a
  `runtime_checkable` two-method Protocol (`read` for the editing-branch buffer
  read, `coerce` for the committed return). Three `@final` stateless accessors
  (`Str`/`Float`/`Color`) carry the per-type miss policy and coercion. The three
  bespoke arbiters are **deleted and every renderer wired to the shared one in
  the same change** (PY-RF-2 behavior-preserving; the three shipped test suites
  are the regression gate, with only key-layout edits permitted).

### Rationale

- **The seam is measured, not guessed.** Diffing three working implementations
  proved the accessor is exactly two methods — the empirical derivation caught
  that the "differences" the earlier sketches listed were fewer than claimed
  (e.g. color's own-suffix buffer key collapsed into a shared convention).
- **The model is data-independent, so verification is free.** The
  DES-048 z-spec's carrier `[VALUE]` is abstract; str, float, RGBA-tuple, and
  int are all valid instantiations, so the *same* ProB model governs the shared
  arbiter and every carrier unchanged — no per-kind spec.
- **Net simplification.** Three ~94-line arbiters became one 129-line generic
  plus three tiny accessors; `WidgetState`'s three suffix families collapsed to
  one.

### Rejected alternatives

- **Per-kind bespoke arbiters forever.** Rejected — the same reconciliation
  logic duplicated per kind, each a place the model must be re-verified by hand.
- **Abstract from the first (or second) kind.** Rejected — the seam would be a
  guess; the rule of three exists precisely so the abstraction is derived from
  evidence, not anticipated.
- **A dedicated accessor per carrier variant** (e.g. `IntValueAccessor`).
  Rejected — a rendering variant expressible as a coercion (int is a `float`
  coerced at the widget seam) does not warrant forking the arbiter's type
  surface; `input_number` reuses `FloatValueAccessor` unchanged, the first proof
  the seam generalizes.

### Consequences

- A new non-atomic kind migrates by supplying a `ValueAccessor` (or reusing an
  existing one) and wiring the shared arbiter — it *inherits* DES-048's proven
  safety instead of re-deriving it. `input_number` was the first such reuse.
- The non-atomic interleaving problem (agent-drive vs. user-edit on shared
  editable state) is **closed for the class**, not per widget.
- `docs/commit_on_idle_reconciliation.tex`'s source-of-record names the shared
  module; its `fuzz` + five ProB goals are the merge gate whenever the arbiter
  or any carrier changes.

### References

- [`docs/architecture/migration/continuous-edit-extraction-design.md`](docs/architecture/migration/continuous-edit-extraction-design.md),
  DES-048 (the mechanism unified here), `continuous_edit_selection.py` /
  `continuous_edit_accessors.py` (the shipped arbiter + accessors),
  `docs/commit_on_idle_reconciliation.tex` (governs all carriers unchanged); bead
  `lux-ld6y`, PR #253.

## DES-050: Value-Proportional Color Channels — Custom Rendering Where Stock ImGui Markers Are Labels

**Status:** accepted. Surfaced by the operator demo of `color_picker`, not by
tests. Renderers: `imgui/color_channel_strip.py`, `imgui/full_color_picker.py`.

Stock ImGui `color_edit3` / `color_picker3` render each RGB channel input with a
**fixed-width color marker** — `RenderColorComponentMarker` draws a
`style.ColorMarkerSize` (default 3px) tab that *identifies* the channel (red for
R, green for G, blue for B). It is a label, not a gauge: R=16 and R=240 draw the
identical sliver. No `ImGuiColorEditFlags` value makes it proportional. The
migration's test suite (2100+ green) could not see this — only driving the live
widget did, which is why the demo gate (DES-039 verification, CLAUDE.md
Development Loop) exists.

### Decision

- **Custom per-channel fill.** `ColorChannelStrip` replaces the stock inline
  `color_edit` channels with a strip that paints its own rect behind each
  channel spanning `width × value/255`, so the fill scales with the value; the
  editable `drag_int` (with `AlwaysClamp`, so typed input honors 0..255) and the
  swatch remain.
- **Full picker composes, does not rebuild.** `FullColorPicker` renders stock
  `color_picker3` with `DisplayHex | NoSidePreview | NoOptions` (which suppresses
  *both* the RGB and HSV marker rows, keeps the marker-free hex readout, and
  seals the right-click that could restore the marker rows) and appends the
  `ColorChannelStrip` for RGB.
- **Reconciliation is untouched.** The custom widgets sit inside a single
  `begin_group`/`end_group` — exactly as stock `ColorEdit`/`ColorPicker` wrap
  their own sub-controls — so ImGui's `EndGroup` aggregates the group's
  active/deactivated status and the DES-048 arbiter still sees the whole widget
  as one item: one commit per gesture, no per-channel or double fire.

### Rationale

- **Correctness the user can see.** A color editor whose channel bars do not
  move with the value is broken UX regardless of a green suite; the fill *is* the
  feedback.
- **Keep what stock does well.** The SV square and hue bar work and are the
  primary editing surface; the composition keeps them and replaces only the
  broken channel rendering.
- **Drop HSV deliberately.** The HSV input row uses the same fixed markers —
  keeping it would relocate the exact bug onto H/S/V. The SV square + hue bar
  already give HSV-space editing, and the hex row (a single text field, no
  per-channel marker) preserves an exact-value readout.

### Rejected alternatives

- **Accept the stock rendering.** Rejected — the channels do not reflect their
  value; the defect the demo caught.
- **Keep the HSV row.** Rejected — reintroduces the fixed-marker bug on H/S/V.
- **Rebuild the popup picker for `picker=false`.** Rejected — `picker=true`
  already provides the full SV/hue picker; the compact inline mode with
  value-proportional channels is the intended `picker=false` surface.
- **A flag or theme tweak.** Rejected — no `ImGuiColorEditFlags` makes the marker
  proportional; the marker is a label by construction.

### Consequences

- Color channel rendering is custom in both modes (`picker=false` inline strip,
  `picker=true` composed picker); both re-verified live for fill-scaling and
  one-commit-per-gesture across the two-widget group.
- `HSV` numeric input is not offered on the migrated `color_picker`; SV/hue +
  hex cover the space marker-free.
- Reinforces the demo-as-verifier discipline: `make check` is the gate for
  compilability and logic; the live demo is the only check for render
  correctness (there is no automated visual-regression layer).

### References

- `imgui/color_channel_strip.py`, `imgui/full_color_picker.py`,
  `color_picker_renderer.py` (the render path), DES-048 (the reconciliation the
  grouping preserves), DES-039 (self-validation + verification), `target.md`
  (render calls stay Display-local); bead `lux-5nn0`, PR #253.

## DES-051: One ABC-Kind Registry — Retire the Six-Copy Element-Factory Ratchet

**Status:** accepted. Modules: `protocol/elements/abc_kind_names.py`,
`abc_kind_spec.py`, `abc_kind_specs.py`, `abc_registry.py`, `abc_kind_table.py`,
`button_sugar.py`; consumers `element_factory.py`, `encoder_factory.py`,
`container_abc_gate.py`, `elements/__init__.py`, `dialog_codec.py`.

The Element-ABC migration (DES-041 fork-don't-mix) was feeding a god-module.
`element_factory.py` grew one per-kind dispatch entry on every migrated kind
(211 → 356 lines across six migrations) and stayed invisible to `make check`
because the OO ratchet compares only *touched* files against the baseline — the
over-target debt surfaced only when `make update-oo` refused. The deeper defect
was that a single fact — *which kinds are on the ABC path* — was hand-copied into
six code enumerations across four modules (`_ABC_KINDS`, `_ABC_LEAF_TYPES`, the
`__new__` decoder dict, the `_decode_legacy` isinstance union, the encoder
`_DISPATCH`, and the `_element_to_dict` union), plus two string sets in the
container gate. The `checkbox` half-migration regression (recorded in
`tests/CLAUDE.md`) is exactly a "these copies drifted" failure. Trimming only the
named file would leave the disease.

### Decision

- **One `AbcElementRegistry` is the single source of truth.** It holds a per-kind
  `AbcKindSpec` (a `runtime_checkable` Protocol, structural — not a base class)
  that knows how to build that kind's decoder from a `TierBinding` DI value
  object and how to encode it. The five class-bearing enumerations collapse into
  registry properties (`leaf_kinds`, `container_kinds`, `abc_types`,
  `build_decoders`, `encoder_dispatch`) consumed by the factory, encoder, and
  aggregator.
- **Three parametrized spec classes, not twelve.** `LeafKindSpec`,
  `DialogKindSpec`, `ContainerKindSpec` carry the per-kind element/decoder/encoder
  *classes as data* (PY-OO-5); the data varies, the behavior does not. One
  `abc_kind_table.py` (`DefaultAbcKinds`) is the sole file a future migration
  edits — one spec value plus one name string.
- **The container gate stays import-light; two data homes, one guard.** The gate
  cannot import element classes (aggregator → container codecs → gate → registry
  → element classes closes a cycle), so kind *strings* live in `AbcKindNames`
  (zero element imports). The heavy spec table and the light name set are the two
  survivors, reconciled by a **fail-loud import-time cross-check**
  (`DefaultAbcKinds.verify_names`): drift is a `RuntimeError` at process start,
  never a silent wire bug. Six hand-copied code enumerations become two data sets
  with a mechanical guard.
- **De-specialize the button sugar.** `canonicalize_button_sugar` moves out of
  the central dispatcher into its own `button_sugar.py` (`ButtonWireSugar`); the
  factory's `decode` loses its only `if kind == "button"` branch, and
  `dialog_codec` re-points to the new home.

### Rationale

- **Kill the ratchet at the root, not the symptom.** The general solution (one
  source of truth) stops *every* future migration from growing this module —
  `element_factory.py` drops 356 → ~130 and per-kind registration becomes
  additive in the table file. A file split would clear 300 lines but leave the
  six-copy drift class intact.
- **Fail-loud over hope.** The layering genuinely forbids a single data home;
  rather than trust manual sync, the cross-check makes divergence impossible to
  ship.
- **Behavior-preserving by construction.** The wire format is unchanged; the spec
  builds the identical decoder per kind with the same DI. Verified: `make check`
  green (2232), `snapshot-parity` 132 (byte-identical corpus), integration 50,
  the 25-kind roundtrip suite 76, plus fidelity tests that the cross-check raises
  on a spec-without-name and a container-mis-declared-as-leaf.

### Rejected alternatives

- **Split `element_factory.py` into two files.** Clears 300 lines but every
  migration still edits both and the six-way duplication survives — symptom, not
  disease.
- **Move only the `__new__` dict to a data module.** Fixes one of six copies; the
  rest drift independently. A partial single-source is not a single source.
- **A bespoke `*KindSpec` class per kind (~12).** Maximum locality, but each new
  kind adds a class not a value; three construction shapes do not justify twelve
  classes.
- **Fold `AbcKindNames` into the registry (one data home).** Ideal but closes an
  import cycle — infeasible under the current layering. The fail-loud cross-check
  is the honest second-best.
- **Self-registering codecs via import side effects.** Eliminates the table but
  makes registration depend on import order and on every codec module being
  imported — a fragile implicit contract. Explicit `DefaultAbcKinds.build()` is
  inspectable, ordered, cross-checkable.

### Consequences

- A future element migration edits `abc_kind_table.py` (one spec) and
  `abc_kind_names.py` (one string); `element_factory.py`, `encoder_factory.py`,
  and `elements/__init__.py` never change for a new kind. The ratchet stops.
- Two data homes remain by necessity, but drift is a hard import-time failure.
- Three implementation deviations from the design, each to avoid a per-file OO
  regression or preserve behavior: button sugar in its own module (not folded
  into `button_codec.py`); the factory uses the module-singleton registry (no
  injectable `__new__` param that would widen `avg_params`); `_decode_legacy`
  keeps the class-based `isinstance(elem, registry.abc_types)` guard (a
  kind-string guard would wrongly reject legacy-forked containers that share a
  kind string but decode to a distinct `Legacy*` class).

### References

- `abc_registry.py`, `abc_kind_spec.py`, `abc_kind_specs.py`,
  `abc_kind_table.py`, `abc_kind_names.py`, `button_sugar.py`;
  `docs/architecture/migration/element-factory-decomposition-design.md` (the
  design); DES-041 (the migration this un-ratchets); `tests/CLAUDE.md` (the
  half-migration regression class); bead `lux-xs7r.2`.

## DES-052: Atomic-Selection Migration — `combo` and `radio` as an Int-Index Checkbox

**Status:** accepted. Modules: `protocol/elements/combo.py`, `radio.py`,
`combo_codec.py`, `radio_codec.py`, `standalone_combo_handler.py`,
`standalone_radio_handler.py`, `display/renderers/{combo,radio}_renderer.py`,
`display/renderers/imgui/{combo,radio}.py`; `PatchField.as_int`.

`combo` (a dropdown) and `radio` (a radio group) are the two remaining
**atomic-selection** interactive leaves — both commit a *discrete* selection, an
`int` index into `items`, exactly as `checkbox` commits a `bool`. They are
`checkbox` with an integer payload: there is no in-progress edit to reconcile, so
**no `ContinuousEditArbiter`**, no commit-on-idle, no echo token. Migrated
together as one minimal family (DES-041's permitted grouping), combo-first then
radio, each fully verified before the next.

### Decision

- **Checkbox reconciliation, not slider.** The stateless renderer reads
  `elem.selected` each frame; `imgui.combo` / `imgui.radio_button` report
  `changed` only on a genuine user pick, giving free echo-suppression and free
  idle-honour. A user selection fires exactly one `ValueChanged(value=<index>)`,
  wrapped for D21 remote dispatch; the built-in `_UpdateSelectedHandler` applies
  `{"selected": <index>}` on the Hub's authoritative copy. The legacy
  Display-local `WidgetState` mirror (which cached the first-seen value and did
  not honour a later Hub re-push) is retired.
- **Value is the selected index (`int`); no protocol touch.** The index rides
  `ValueChanged.value`'s existing `bool | int | float | str` arm — no union
  widening, no new `InteractionEventBuilder` arm. The element wire
  `{kind, id, label, items, selected}` is byte-identical for tooltip-less
  elements (snapshot-parity holds); the legacy `{index, item}` interaction dict
  is dropped (no consumer read `item`; the Hub recomputes it from
  `items[selected]`).
- **`apply_patch` re-checks the whole element.** `selected`'s validity depends on
  `items`, so a combined `{items, selected}` patch is judged on final state and
  rolled back atomically if the new index is out of range — the slider pattern.
- **`validate()` rejects, it does not clamp (DES-039).** An out-of-range or
  itemless-nonzero `selected` returns an error and the malformed tree is never
  rendered; the agent is told to fix its data. This deliberately replaces the
  legacy renderers' *silent clamp-to-0 + warning log* — the silent-accept-invalid
  the self-validation model closes. Operator-ratified.
- **`PatchField.as_int`** — a shared boundary coercer on the class that owns the
  other `as_*` coercers (PY-OO-5); rejects `bool` (an `int` subclass) and non-int
  (an index must be an exact whole number).
- **Lands additively (DES-051).** Each kind is one `abc_kind_table` spec + one
  `MIGRATED_ABC_KINDS` + one `INTERACTIVE_KINDS` string; the capability guard now
  requires each kind's handler. Legacy fork-wiring removed (fork-don't-mix), but
  each element is **kept in `element_renderer._NATIVE_DISPATCH`** exactly as the
  checkbox exemplar does — for DES-042 transitional rendering of a migrated leaf
  nested in a still-legacy container.

### Rationale

- **Reuse the proven atomic path.** `checkbox` already demonstrated the
  no-arbiter atomic-selection reconciliation; combo/radio are a mechanical
  int-payload replay, so the migration carries no new reconciliation risk.
- **Reject over clamp is correctness the agent can act on.** A silently-clamped
  out-of-range index hides the agent's data bug; surfacing it is the whole point
  of self-validation.
- **Int index over a discriminated selection type.** `items` is genuinely open
  data and `selected` is a total `int` (default 0), not an absence — no Optional,
  no discriminated state to model.

### Rejected alternatives

- **Two separate PRs.** Combo and radio are one design applied twice (same wire,
  same value semantics, same event, same reconciliation) — one rollback-coherent
  unit; two PRs duplicate an identical review and split the unit.
- **Keep the legacy clamp-to-0.** Rejected — it is the silent-accept-invalid
  DES-039 exists to close.
- **Carry the `{index, item}` interaction dict.** Rejected — `item` is derivable
  from `items[selected]` and no consumer reads it; the scalar index is the
  minimal payload.
- **Share a common atomic-selection abstraction across checkbox/combo/radio.**
  Rejected for now — checkbox is a `bool` toggle, combo/radio are `int` indices;
  the only shared shape is "read the value each frame, fire once," which the
  exemplar already expresses. Two near-identical `checkbox` clones do not justify
  a premature base abstraction (composition/Protocol already carry the contract).

### Consequences

- A future selection-style kind is a checkbox-shaped clone landing as one table
  entry; `selectable` (a `bool`-in-a-list, nearer checkbox) is the next and last
  B2 kind.
- Out-of-range selections now fail loud at validation — a behavior change from
  legacy, aligned with every other migrated element.
- Process note: this migration hit the shared-worktree parallel-agent collision
  the standards warn about (a suspected-dead agent recovered while a replacement
  edited the same tree, briefly orphaning combo's baseline). Recovered by a
  leader proxy-commit + a clean whole-tree rebaseline; the lesson is to isolate
  concurrent element migrations in separate worktrees.

### References

- `combo.py` / `radio.py` (elements), the `*_codec.py` / `standalone_*_handler.py`
  / `*_renderer.py` / `imgui/*.py` sets, `PatchField.as_int`;
  `docs/architecture/migration/combo-radio-design.md` (the design); DES-051 (the
  registry this lands through), DES-042 (transitional rendering), DES-039
  (self-validation), DES-041 (fork-don't-mix / minimal family); `checkbox` (the
  exemplar); beads `lux-qnyf`, `lux-r2ay`.

## DES-053: `selectable` as a Bool Checkbox in a List Row — the Shared-Handler Payoff

**Status:** accepted. Modules: `protocol/elements/selectable.py`,
`selectable_codec.py`, `display/renderers/selectable_renderer.py`,
`display/renderers/imgui/selectable.py`; `protocol/elements/inputs.py` deleted.

`selectable` is the last B2 kind and the simplest atomic leaf: a `bool` on/off
toggle that paints as a clickable list row via `imgui.selectable` instead of
`imgui.checkbox`. It carries no index-into-`items` (that is combo/radio), so
there is no cross-field invariant, no `apply_patch` override, no `validate()`
override, and — being atomic — no `ContinuousEditArbiter`. It maps onto the
`checkbox` exemplar field-for-field with wire key `selected` (bool) in place of
`value`. With three prior atomic kinds (checkbox/combo/radio) already sharing
`ApplyPatchOnChange` (DES-052), `selectable` is the **payoff case** — it reuses
the shared handler with **zero** new handler code.

### Decision

- **Reuse the shared handler.** The decoder installs
  `ApplyPatchOnChange(elem, field="selected")` — the `ChangedField =
  Literal["value","selected"]` alias already carries `"selected"` (combo/radio's
  arm), so no new handler module and no widening. `NoopValueHandler` +
  `build_standalone_value_handler_decoder` are reused for the standalone path.
- **No `apply_patch` / `validate` override.** A `bool` toggle plus a `str` label
  is always well-formed — there is no invalid-but-representable state to police.
  `SelectableElement` inherits the ABC no-error `validate()` default. This is
  the *component-appropriate* DES-039 answer ("no constraints"), not a gap; a
  non-bool `selected` is rejected at the codec boundary (PY-EH-1), and the gate
  asserts the positive tree-walk + codec rejection rather than a nonexistent
  nested-rejection path.
- **Always emit `selected`.** The encoder serializes `selected` unconditionally
  (an unselected row is `{…,"selected":false}`), matching checkbox/combo/radio.
  **We do not preserve the legacy omit-when-false quirk** — correctness and
  sibling-consistency decide, not legacy byte-identity (operator ruling). The
  legacy omit-when-false pinning test is flipped to assert always-emit. Tooltip
  round-trips (legacy silently dropped it).
- **Delete `inputs.py`.** `selectable` was `InputsRegistry`'s only remaining
  registration; once it lands on the ABC registry the module is empty, so it and
  its `build_element_codec` call are removed (PL-PP-1, no tombstone).
- **Additive DES-051 landing.** One `abc_kind_table` spec + one
  `MIGRATED_ABC_KINDS` + one `INTERACTIVE_KINDS` string; the capability guard
  requires its handler. Kept in `_NATIVE_DISPATCH` (DES-042) for a selectable
  nested in a still-legacy container. No protocol touch — the bool rides
  `ValueChanged.value`'s existing arm.

### Rationale

- **The dedup pays off exactly as intended.** The combo/radio rule-of-three
  extraction (DES-052) existed so the next atomic kind would land with no new
  handler; `selectable` is that kind. A vacuous `validate()` and a reused handler
  are the right minimalism, not under-engineering.
- **Correctness over legacy.** An always-emitted `selected` is the correct,
  consistent wire; the legacy space quirk gets fixed, not preserved.

### Rejected alternatives

- **A selectable-specific update handler.** Rejected — the shared
  `ApplyPatchOnChange(field="selected")` already covers it; a bespoke handler
  would re-introduce the duplication DES-052 removed.
- **Preserve the legacy omit-when-false wire.** Rejected — matching legacy is
  never a goal; a value that exists is serialized.
- **A validate() override for symmetry with combo/radio.** Rejected — there is
  no selectable invariant to express; a bool+label is always valid, and an empty
  override asserting nothing is noise.

### Consequences

- B2 (interactive value inputs) is complete: slider, input_text, input_number,
  color_picker, combo, radio, selectable all migrated.
- `element_renderer.py` (over-target, 467) took the `selectable_renderer`
  property; the +3 was **offset to net-zero, not rebaselined up** — the third
  time this over-target file absorbed a per-kind renderer property and was
  trimmed back (combo, radio, selectable). Its continued accretion is a signal it
  should be decomposed before the B1 batch adds more.
- `selectable.py`'s dataclass→ABC growth (46→170) is the established, ratified
  ABC-migration baseline drift.

### References

- `selectable.py` / `selectable_codec.py` / `selectable_renderer.py` /
  `imgui/selectable.py`; `value_change_handlers.py` (the shared handler reused);
  `docs/architecture/migration/selectable-element-design.md`; DES-052 (the dedup
  this pays off), DES-051 (the registry), DES-042 (transitional rendering),
  DES-039 (self-validation); `checkbox` (the exemplar); bead `lux-07f5`.

## DES-054: One Render-Dispatch Table — Retire `_NATIVE_DISPATCH`, Route Through the Factory

**Status:** accepted. Modules: `display/element_renderer.py`,
`display/renderers/imgui/factory.py`, `display/renderers/tooltip_painter.py`,
`display/renderers/imgui/__init__.py`,
`display/renderers/{tree,plot,modal,leaf_widget}_renderer.py`. Design doc:
`docs/architecture/migration/element-renderer-decomposition-design.md`.

`element_renderer.py` was the worst-over-target module (467 lines) and, worse,
it *grew* on every atomic-kind migration — each added a `_<kind>_renderer`
property, offset by hand to keep the OO ratchet from recording the debt going
up. The root cause was not size: `element_renderer._NATIVE_DISPATCH` was a
**second copy** of `imgui/factory.py`'s `_DISPATCH` — two hand-maintained tables
carrying the same fact (which kind paints via which renderer), reached by two
routes (the ABC path via `Element.render()` → the factory adapter; the native
path via `_dispatch_native`). The checkbox half-migration regression was that
drift. This is DES-051's disease (the six-copy element-factory ratchet) one
layer down, in the render tier.

Decomposed in two rollback-coherent PRs. PR1: extract the three un-extracted
inline legacy paint bodies (`tree`/`plot`/`modal`) into `@final` renderer classes
behind a `runtime_checkable LeafWidgetRenderer` Protocol — behaviour-preserving,
467→358. PR2 (the core of this decision): delete the duplicate.

### Decision

- **Delete `_NATIVE_DISPATCH`; route through the one factory.** `render_element`'s
  ABC branch resolves through the `ImGuiRendererFactory` — the registry that
  already holds the kind→adapter mapping — via a new
  `factory.handles(elem) -> TypeGuard[AbcElement]` predicate (PY-EH-4: a
  narrowing predicate; `__call__` keeps raising for a genuinely-unknown type).
  This generalises what `_render_dialog` already did, so `_render_dialog` folds
  into the shared `factory(elem).begin/paint/end` branch.
- **Explicit factory route, not `elem.render()`.** `_wrap_abc_elements`
  (`server.py`) binds the real factory only on top-level ABC elements and their
  ABC subtree; a migrated ABC leaf nested in a *legacy* container keeps the
  `RAISING_FACTORY` sentinel, so `elem.render()` would raise. The ElementRenderer
  drives its own real factory explicitly. This *strengthens* DES-042: the
  transitional (legacy-nested-leaf) path and the top-level ABC path now resolve
  the identical adapter — byte-identical paint, drift removed by construction
  rather than by discipline.
- **Stateless renderers per-paint; break the cycle.** Each ImGui adapter
  constructs its stateless renderer per paint from `factory.widget_state` (the
  renderers hold no frame-spanning state beyond `WidgetState`, verified for
  slider/input_text/input_number/color_picker). `apply_tooltip` moves onto a new
  factory-owned `TooltipPainter` value class, so adapters stop reaching back
  through `factory._element_renderer`; that back-reference is deleted and the
  `ElementRenderer ⇄ factory` import cycle is broken (PL-CU-2 — `factory.py`
  imports `element_renderer` only under `TYPE_CHECKING`).
- **Minimal residual table.** The native table is trimmed 15 → 4 — only the
  pre-ABC display leaves with no adapter (`image`/`separator`/`spinner`/
  `markdown`). It can only lose rows and empties in the B1 basics migration; the
  four are NOT given adapters now (that would front-run B1).

### Rationale — shrink-as-migrate

After this, migrating a kind adds one row to `factory._DISPATCH` and one spec to
`abc_kind_table` (the DES-051 sources) and **deletes** its legacy `_RENDERERS`
row and delegator — `element_renderer.py` is never edited to *add* a kind again
and loses lines per migration. The per-kind accretion that forced hand-offsets
is gone. `element_renderer.py` dropped 467 → 251 across the two PRs (under the
300 target); `factory.py` (120 → 124) absorbed `handles()` + `apply_tooltip`,
offset manually to stay well under target — genuine paydown, not
rebaseline-absorption. (One ratified `--rebaseline`: deleting 10 zero-param dead
accessors raised element_renderer's mean `avg_params` 0.68 → 1.0 — a mean-shift
artifact, still 4× under the 4.0 threshold, on a file that shed 107 lines.)

### Rejected alternatives

- **Per-family split of the renderers.** Clears the line count by relocating
  mass but keeps `_NATIVE_DISPATCH` growing one row per migration — symptom, not
  disease (the "split the file" option DES-051 rejected). Rejected.
- **A new `RenderKindRegistry`.** The Display already has that registry — the
  factory. A second one beside it re-creates the many-copies drift. Rejected;
  its spirit (one additive source) is adopted via the factory.
- **`elem.render()` for the ABC branch.** Would raise on a legacy-nested ABC leaf
  (sentinel factory). Rejected in favour of the explicit factory route.
- **Give the four residual leaves adapters now.** Front-runs their B1 migration.
  Rejected; keep the shrinking 4-entry residual table.

### Consequences

- The render dispatch has one authoritative table. A future kind migration is
  additive to the factory + subtractive from element_renderer.
- Optional hardening (a later PR): a DES-051-style import-time drift guard
  asserting `factory._DISPATCH` covers exactly the ABC registry's kinds, so a
  migration that adds a codec spec but forgets the adapter fails at process
  start, not as a silent `[unsupported element]`.
- The dead `ProgressRenderer` was removed (its adapter draws directly,
  byte-identical).

### References

`docs/architecture/migration/element-renderer-decomposition-design.md`;
`element_renderer.py`, `imgui/factory.py`, `tooltip_painter.py`; DES-051 (the
same duplicate-table lesson, one layer up), DES-042 (transitional rendering,
strengthened here), DES-041 (fork-don't-mix); bead `lux-m4r8`.

## DES-055: One Code Path — Typed Hub Operations, a REST Front Door, Thin Adapters

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
