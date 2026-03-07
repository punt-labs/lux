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

```
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
