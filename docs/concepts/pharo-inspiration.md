# Pharo Display Server: Technical Spikes

> **Status: Not approved alternative concept.**
> This document explores a different direction centered on Pharo. It is not
> the canonical Lux architecture, is not an approved plan, and is not under
> active development. Do not use it to guide implementation. See
> `docs/architecture/target/target.md` for the current target design.

## Context

Lux is ~25% done reimplementing a subset of Morphic on top of ImGui with a JSON
protocol. The hypothesis: starting from Pharo — which already has Morphic, live
introspection, and a persistent image — is a shorter path to the endgame (a live
environment where agents compose arbitrary UI and engineers interact visually).

The architecture: two agents, two domains. Claude Code owns the project (Go,
Python, Swift, git, tests, CI). A Pharo agent owns the UI — it receives specs,
browses its own image, writes Morphic code, and presents the result. Only intent
crosses the wire, not implementation.

Each spike below validates one assumption. Spikes are ordered by dependency —
later spikes build on earlier ones. Each should take 1-3 days and produce a
working demo, not a design doc.

---

## Spike 1: Claude API Client in Smalltalk

**Question:** Can a Pharo process call the Claude Messages API, stream
responses, and handle tool use?

**What to build:**

- HTTP client using Zinc (`ZnClient`) that POSTs to `https://api.anthropic.com/v1/messages`
- Streaming via SSE (server-sent events) — Zinc supports chunked transfer
  encoding; parse `event: content_block_delta` / `message_stop` frames
- Tool use round-trip: send a message with tool definitions, receive a
  `tool_use` content block, return a `tool_result`, continue the conversation
- API key from environment variable or image config

**Success criteria:**

- Single-turn conversation with tool use works end-to-end
- Streaming token output to Transcript
- Multi-turn conversation with state

**Risks:**

- Zinc's SSE/chunked streaming may need custom handling — Pharo's HTTP stack
  is synchronous by default
- JSON parsing performance for large responses (Pharo's `STON` or `NeoJSON`)

**Output:** `ClaudeClient` class with `#sendMessage:tools:` and streaming
callback. Packaged as a Pharo package loadable via Metacello.

---

## Spike 2: MCP Server in Pharo

**Question:** Can Pharo host an MCP server that Claude Code connects to via
stdio or WebSocket?

**What to build:**

- JSON-RPC 2.0 handler: parse requests, dispatch to tool methods, return results
- Stdio transport: read from stdin, write to stdout (for direct Claude Code
  integration via plugin config)
- WebSocket transport: Zinc WebSocket server (for mcp-proxy integration, same
  pattern as quarry)
- Tool registration: a Smalltalk method annotated or registered as an MCP tool
  with name, description, and JSON Schema parameters
- Implement 3 proof-of-concept tools: `ping`, `evaluate` (run Smalltalk code),
  `browseClass` (return class info)

**Success criteria:**

- Claude Code connects to the Pharo MCP server (via stdio or mcp-proxy)
- Claude calls `evaluate` with Smalltalk code, gets the result back
- Claude calls `browseClass` with a class name, gets methods/instVars/comment

**Risks:**

- Stdio transport requires Pharo to read stdin without blocking the UI thread —
  needs a background `Process` (green thread)
- JSON Schema generation from Smalltalk method signatures isn't automatic

**Output:** `McpServer` class with transport abstraction and tool registry.

---

## Spike 3: Image Introspection Toolkit

**Question:** Can an agent running inside Pharo browse the image well enough to
write correct Morphic code without external help?

**What to build:**

- Introspection facade: a single object that wraps SystemNavigation, method
  dictionaries, and cross-references behind a clean API
- Batch query support: one call returns class comment + instVars + superclass
  chain + protocols + method source for key selectors
- Search: substring and regex across all method source
  (`allMethodsWithSourceString:`)
- Context-rich error recovery: when `Compiler evaluate:` fails, return the
  error plus suggestions (did-you-mean selectors, matching methods on the class)
- Cost measurement: instrument query times — target single-digit milliseconds
  per batch query (see Success criteria)

**Success criteria:**

- Agent can go from "I want to show a table" to finding `FTTableMorph`,
  reading its API, and writing working code — using only introspection queries
- Round-trip time for a batch query < 5ms
- Error recovery suggests the correct selector >80% of the time

**Risks:**

- Morphic's API surface is large and inconsistent across Pharo versions
- Some Morphic classes have undocumented protocols — the agent may need curated
  examples, not just raw browsing

**Output:** `ImageBrowser` class. Also produces a report on Morphic API surface
area — which classes are well-documented, which need curated examples.

---

## Spike 4: Agent Loop Inside the Image

**Question:** Can an LLM agent run as a Pharo process — receiving tasks,
browsing the image, writing code, evaluating it, iterating on errors — all
inside the image?

**Depends on:** Spike 1 (Claude API client), Spike 3 (introspection toolkit)

**What to build:**

- `PharoAgent` class: holds a Claude API conversation, a workspace (persistent
  bindings across evaluations), and the introspection toolkit
- Agent loop: receive a task (natural language spec) → compose a system prompt
  with available Morphic classes → call Claude API → receive Smalltalk code →
  evaluate → if error, feed error + suggestions back to Claude → retry → return
  result
- Tool definitions for the agent's own use: `browseClass`, `browseMethod`,
  `searchCode`, `evaluate`, `inspect` — these are calls the Claude model makes
  via tool use, dispatched locally within the image
- Workspace persistence: bindings from previous evaluations are available in
  subsequent ones (like a REPL)

**Success criteria:**

- Given "show a table with columns Name and Status, 5 sample rows," the agent
  browses Morphic, writes code, and a table appears — with no human intervention
- Given a spec that requires an unfamiliar Morphic class, the agent discovers it
  via browsing (not from training data)
- Error recovery: agent handles at least 2 compile/runtime errors before
  producing working code

**Risks:**

- Claude's Smalltalk generation quality — even with introspection, the model
  may produce syntactically valid but semantically wrong code
- Token cost: each introspection call adds to the conversation; a complex UI
  may require many browsing steps
- Agent loop needs to be bounded — infinite retry on unfixable errors

**Output:** `PharoAgent` running in a Pharo `Process`. Demo: give it 5
different UI specs of increasing complexity, measure success rate and
iteration count.

---

## Spike 5: Claude Code to Pharo Agent Bridge

**Question:** Can the Claude Code agent (terminal) send a UI spec to the Pharo
agent and receive interaction events back?

**Depends on:** Spike 2 (MCP server), Spike 4 (agent loop)

**What to build:**

- MCP tool `showUI` exposed by Pharo's MCP server: accepts a natural language
  or structured spec, dispatches to the Pharo agent, returns a handle
- MCP tool `receiveEvent`: blocks (with timeout) until the user interacts with
  the UI, returns the interaction (button click, selection, form submission)
- MCP tool `dismissUI`: tear down a specific UI
- Spec format: start with natural language ("show a dashboard with..."), evolve
  to structured specs if needed
- Event format: `{element: "approve-button", action: "click", value: true}`

**Success criteria:**

- Claude Code agent (in terminal) calls `showUI` with a spec, Morphic UI
  appears in Pharo, user clicks a button, Claude Code receives the event
- Full round-trip: Claude Code sends spec → Pharo agent builds UI → user
  interacts → Claude Code receives result → Claude Code continues its work
- Latency from spec to visible UI < 10 seconds (including agent browsing and
  code generation)

**Risks:**

- Async coordination: Claude Code sends spec and needs to wait for the UI
  to be built before polling for events
- Pharo agent may be mid-task when a new spec arrives — needs a task queue

**Output:** Working demo of the two-agent architecture. Claude Code runs a
normal coding task, sends a UI spec for approval, engineer approves in Pharo,
Claude Code continues.

---

## Spike 6: Persistence and Image Management

**Question:** How does the Pharo image lifecycle work for a developer tool
that runs daily?

**What to build:**

- Image startup: auto-start MCP server and Pharo agent on image launch
- Image save discipline: when and how to snapshot (on clean shutdown? periodic?
  never — treat as ephemeral?)
- Package management: all custom code in Metacello packages, loadable into a
  fresh image. The image is reproducible, not precious.
- Distribution: script that downloads PharoVM + base image, loads packages via
  Metacello, produces a ready-to-run directory
- Integration: launchd/systemd service file (same pattern as quarry daemon)
- Crash recovery: what happens when the image corrupts? How fast can you
  rebuild from packages?

**Success criteria:**

- Fresh image to working display server in < 60 seconds
- Image can be deleted and rebuilt with zero data loss (all state is in packages
  or external storage, not in image-specific object state)
- Daemon survives host reboot via service manager

**Risks:**

- The "image is the database" model conflicts with "image is disposable" — need
  to decide which objects persist in the image vs. externally
- Pharo VM startup time (~1-2s) is fine for a daemon but matters if spawned
  per-session

**Output:** `install-pharo-display.sh` script. Makefile targets for build,
clean, rebuild. Service file.

---

## Spike Order and Dependencies

```text
Spike 1 (Claude API)     Spike 2 (MCP Server)
         \                     /
          \                   /
           Spike 3 (Introspection)
                  |
           Spike 4 (Agent Loop)
                  |
           Spike 5 (Bridge)
                  |
           Spike 6 (Persistence)
```

Spikes 1, 2, and 3 are independent and can run in parallel.
Spike 4 requires 1 + 3.
Spike 5 requires 2 + 4.
Spike 6 can start after 5 but doesn't strictly depend on it.

## Go / No-Go Decision

After Spike 4, you know whether the Pharo agent can reliably generate Morphic
UI from specs. If it can't — if Smalltalk generation quality is too low even
with full introspection — then the approach doesn't work and Lux (or a different
host) is the right path. Spike 4 is the gate.

After Spike 5, you know whether the two-agent architecture produces a better
engineer experience than Lux's JSON element trees. If the round-trip is too
slow or the UIs are too crude, the architecture is sound but the execution
needs iteration.

## What Lux Becomes

If the spikes succeed, Lux's role changes. The `punt-lux` Python package
becomes a compatibility layer — it translates Lux's existing JSON protocol
into specs for the Pharo agent. Existing plugins that use `show_table`,
`show_dashboard`, `show_diagram` continue to work. New UI work goes directly
through the Pharo agent.

The ImGui display server (`lux display`) is retired when the Pharo display
server reaches feature parity on the core use cases: tables, dashboards,
diagrams, interactive forms.
