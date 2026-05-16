# Research Spikes

Early-stage research spikes that validated Lux's core design decisions.
The code is no longer runnable (APIs have changed), but the findings
document the reasoning behind the architecture.

## Spike A: imgui-bundle Viability

**Question:** Can imgui-bundle serve as the rendering backend for a
Python-driven display server?

**Finding:** Yes. imgui-bundle (via hello_imgui) provides a
batteries-included ImGui integration with automatic window management,
font loading, and OpenGL backend. The Python bindings are complete
enough for a full display server. The main risk — Python GIL blocking
the render loop — is mitigated by non-blocking socket I/O with
`select()` at zero timeout.

## Spike B: IPC + Render Loop Architecture

**Question:** What IPC mechanism connects the MCP server to the display?

**Finding:** Unix domain sockets (stream mode) with length-prefixed
JSON framing. Evaluated against: datagrams (payload size risk), named
pipes (unidirectional), shared memory (over-engineered). Unix sockets
provide bidirectional, backpressure-aware, cross-platform (macOS +
Linux) transport with TCP-like reliability. The display server polls
with `select()` at zero timeout each frame — no threading needed.

## Spike C: Protocol Design

**Question:** What wire format carries element trees and events?

**Finding:** Length-prefixed JSON. Each message is a 4-byte big-endian
length prefix followed by a JSON object. Message types identified by a
`"type"` field. Elements identified by a `"kind"` field. This is the
simplest format that any language can produce — no protobuf, no msgpack,
no framework dependency. The protocol is the API surface.

## Spike D: Extended JSON Vocabulary

**Question:** How many ImGui primitives can be driven by JSON element
dicts?

**Finding:** 24 element kinds covering text, buttons, images, sliders,
checkboxes, combos, inputs, radios, color pickers, tables, plots,
trees, selectables, progress bars, spinners, markdown, draw canvases,
modals, groups, tab bars, collapsing headers, windows, and separators.
Each element is a dict with a `kind` field. Container elements nest
children. The vocabulary is sufficient for dashboards, data explorers,
and form-based UIs.

## Spike E: Code-on-Demand

**Question:** Can agents send Python render functions to execute inside
the display server?

**Finding:** Yes, but it was removed from the product. The spike proved
the mechanism works (AST safety check + consent dialog + sandboxed
exec), but code-on-demand contradicts Lux's core value proposition:
ImGui via JSON. The JSON protocol is language-agnostic; code-on-demand
is Python-only. The feature was shipped in v0.15 and removed in v0.17.

## Spike F: Interactive Demo

**Question:** End-to-end validation of the interactive widget system.

**Finding:** All interactive elements (sliders, checkboxes, combos,
inputs, radios, color pickers) generate interaction events that flow
back to the MCP server via `recv()`. Widget state persists across
frames via `WidgetState`. The push-based event system (background
listener thread + callbacks) eliminates polling.

## Demos (historical)

Six demos were written to exercise the display client library directly
(bypassing MCP):

- `containers.py` — nested layout containers (groups, tabs, headers, windows)
- `dashboard.py` — multi-window dashboard with draw canvases
- `data_viz.py` — tables, plots, trees, selectables
- `hello_callback.py` — push-based event handling (menu click → frame)
- `interactive.py` — all interactive widget kinds
- `menu_bar.py` — agent-extensible custom menus

These demos used `DisplayClient` (formerly `LuxClient`) directly and
are no longer maintained. The current way to exercise Lux is through
MCP tools or the `/lux:beads` and `/lux:dashboard` skills.
