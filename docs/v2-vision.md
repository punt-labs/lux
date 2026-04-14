# Lux v2 Vision

> Captured from a design conversation between Jim Freeman and Claude Agento,
> April 2026. This is the north-star intent, not a specification.

## What Lux is

Lux is a Python-native display compositor for AI agents. It provides a
persistent local service that agents connect to, renders their content, and
grows new capabilities on demand through LLM-authored extensions.

It is not a GUI framework. It is not a web stack. It is a runtime that hosts
Python rendering and coordinates multiple agents sharing one display.

## The core problem it solves

N-to-1 agent visibility. Multiple Claude Code instances --- local sessions,
remote SSH sessions, Anthropic cloud API processes --- all producing
intermediate output that humans need to see. One shared display surface,
multiple agent peers, clear attribution, coordinated lifecycle.

Today's answer is terminal scrollback plus ad hoc screenshots. The vision is a
live, structured, introspectable display that every agent can write to.

## The architectural shape

**Closed core, open extension surface.** Open-Closed Principle applied
honestly: the core is small and stable; everything user-visible is an
extension.

Core provides:

- Transport (Unix socket + TCP with TLS for remote)
- Protocol dispatch (message arrives, look up handler)
- Extension registry (element kinds, services, themes)
- Extension loader (scan, validate, register, crash-isolate)
- Frame management (the organizing primitive --- where rendered content lives)
- Primary ImGui render loop + event loop
- Safety wrapper + consent model
- Service layer (HTTP endpoints)

Everything else --- text, button, table, window, plot, markdown, image,
applets, themes, debug tools, agent SDK --- is an extension. Lux ships with a
curated starter pack; power users install from community; agents author on
demand.

## Three rendering modes

Every extension declares how it renders:

- **`imgui`**: extension runs each frame in Lux's ImGui context. Preferred
  mode. Full interactivity, single-window UX.
- **`texture`**: extension produces a pixel buffer; Lux uploads and displays as
  an ImGui image. For matplotlib, PIL, plotly snapshots --- the Python
  data-science ecosystem. Interactivity is limited but clicks can be forwarded.
- **`window`**: extension owns its native OS window. For Qt, tkinter, Jupyter
  kernels, Pharo widgets --- anything that can't live inside ImGui. Lux tracks
  lifecycle and coordinates focus but doesn't composite pixels. IDE-style
  separate windows, weakly managed.

Event loops don't merge. Each mode lives at its natural substrate. Lux doesn't
fight them; it coordinates around them.

## Two interfaces

**MCP** --- the rigid adapter for tool-call use cases. Claude Code calls
`show()`, gets an ack. Deterministic, typed, testable. Existing integration
pattern preserved.

**Service API** --- ollama-shaped HTTP. The real interface. Endpoints for
rendering, introspection, extension management, event streaming. Any agent, any
transport, any machine. MCP is a thin translation layer on top of this.

Both share the same backend: one display, one extension registry, one session.

## The LLM-authoring loop

When an agent wants to render something Lux can't currently render:

1. Agent calls service endpoint with an unknown element kind.
2. Lux returns a capability error pointing at `/api/extensions/author`.
3. Agent POSTs a description of what's needed.
4. Lux's optional in-display agent generates the extension (manifest + renderer
   code + tests).
5. Consent dialog shows the code; user approves per the configured permission
   mode.
6. Extension installs to `~/.lux/extensions/`.
7. Agent retries. Renders.

Next time any agent (this user or anyone who installs from the community repo)
needs that element, it works. Lux grows its vocabulary by use.

This is the magic. "Lux cannot support X" is replaced with "Lux can support X,
and now it does, persistently, for this user and optionally for the community."

## The in-display agent

Optional but architecturally central. Same shape as
`claude-agent-sdk-smalltalk`'s Agent SDK:

- Built on the Anthropic Python SDK
- Tool-use loop driven by a `LuxExchange` (analog to `ClaudeExchange`)
- Tools are classes operating on the live display: InstallExtension,
  AuthorExtension, ShowScene, UpdateScene, IntrospectFrames, RunPython,
  Screenshot, and so on
- Leaf commands + composite commands with transactional rollback (Gang-of-Four
  Composite)
- Five-mode permission policy: Plan, Default, Accept-edits, Bypass, DontAsk

External agents drive this via the service API. Internal users interact via a
Lux chat frame (the Workbench equivalent, itself an extension).

The display becomes its own operator environment --- a Python-native analog to
Pharo's image, bounded by what Python's dynamism supports: hot-loading,
monkey-patching, exec-in-namespace, no true `become`, no image persistence.

## Persistence and community

Extensions persist in three tiers:

- **User-local** (`~/.lux/extensions/`) --- survives restart, per-user
- **Project-local** (`.lux/extensions/`) --- checked into repo, scoped to
  project
- **Community registry** --- a curated repo of extensions installable via
  `lux ext install <name>`. GitHub-hosted with minimal app-store
  functionality: ratings, download counts, safety classifications, provenance.
  Extensions have versioning and declared compatibility with Lux core versions.

The LLM-authoring loop can publish back to the community: an extension authored
for one user becomes available to all. Ratings and usage data surface which
extensions are battle-tested versus experimental.

## The `/help` contract

Every Lux instance exposes `/help` (or `/api/capabilities`), auto-documenting
from the live registry:

- What element kinds are installed right now
- What services are registered
- What conventions this instance follows
- What permission mode is active
- What extensions are available but not loaded

An agent that has never seen this Lux instance reads `/help` first and learns
what's real. Same contract as postern's `/help` endpoint --- runtime truth, not
static documentation.

## The Pharo relationship

Complementary, not competing.

- **Pharo** is the ambitious live-environment substrate. Full image
  persistence, become, Morphic, introspection everywhere. Where novel UI
  patterns get invented, where agents can live-code.
- **Lux** is the pragmatic Python-native substrate. Good enough dynamism for
  hot-loading extensions. Native to the Python ecosystem agents already use.
  Coordinates with Pharo via window-mode extensions that talk to postern.

An extension authored in Pharo (leveraging Morphic's design surface) can be
exported as a Lux window-mode extension that hosts Pharo-rendered content via
postern. Or Pharo can remain separate; the two connect through their agent SDKs
and shared protocols.

## What's explicitly out of scope

- Being a web platform. Chrome, Electron, webviews are not in the vision.
- Being a GUI framework. Lux hosts; it doesn't define widgets as first-class
  types in the core.
- Being an LLM runtime. The in-display agent calls Anthropic; it doesn't host
  inference locally.
- Being a window manager. OS-native windows are coordinated, not composited.
- Being universal. If your content genuinely needs web embedding, use a
  web-native display. Lux is Python's answer, not everything's answer.

## How this differs from Lux v1

Lux v1 is a fixed 27-element vocabulary rendered by a hardcoded ImGui
dispatcher. Agents use what's there or fall back to render_function. There's no
service API, no extension system, no in-display agent, no authoring loop.

The v2 vision is a different product that happens to share Lux v1's protocol
shape and ImGui-based rendering. The existing code is a starting point --- the
ImGui loop, the frame system, the protocol, the client library, the MCP
adapter --- but the architectural center of gravity shifts.

## Why it's worth doing

Three things converge:

1. **Agents need visibility** into what they're doing. Terminal scrollback is
   inadequate; screenshots are ad hoc.
2. **LLMs can write extensions on demand**, meaning fixed vocabularies are no
   longer the right trade-off.
3. **Python already has the ecosystem** --- matplotlib, Jupyter,
   Pharo-via-postern, pyte, ImGui, Qt, tkinter. No single framework wins; a
   compositor coordinates them.

The combination is the product. Not "ImGui with more widgets" --- a
Python-native, agent-first, extensible display surface where "Lux can't do X"
is solved at runtime.

## What v1 proved

- The display has value. The beads browser is used daily across multiple repos.
- Per-project frames with multi-client ownership works. Multiple agents sharing
  one display surface is real.
- The hook architecture (PostToolUse auto-refresh) makes the display feel live.
- The protocol-as-API design (JSON over socket) is sound and language-agnostic.
- 629 tests + Z specification + model checking gives confidence in the core.

## What Pharo proved

- A self-extending system is valuable. The postern + agent SDK + workbench
  stack lets an agent browse the image, write new code, test it, and commit ---
  all without leaving the running environment.
- Agent-authored code that persists and is reusable changes the economics of
  building UI. Novel problems get solved once and shared.
- The Composite pattern for tool commands (leaf + composite, transactional) is
  the right shape for agent tools.
- Five-mode permission policy (Plan / Default / Accept-edits / Bypass /
  DontAsk) matches real trust levels.

## Lux v2 = v1 display + Pharo self-extension + Python ecosystem

That's the one-line summary. Take what works from v1 (protocol, frames, ImGui,
hooks, MCP adapter), add the self-extension model from Pharo (agent SDK, tool
commands, authoring loop, community persistence), and ground it in Python's
package library (matplotlib, pyte, Qt, etc. via three rendering modes).
