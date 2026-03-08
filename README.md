# lux

> A visual output surface for AI agents.

[![License](https://img.shields.io/github/license/punt-labs/lux)](LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/punt-labs/lux/test.yml?label=CI)](https://github.com/punt-labs/lux/actions/workflows/test.yml)

Lux gives AI agents a window they can draw into. It runs an ImGui display server on the local machine, connected by Unix socket IPC. Agents send JSON element trees via MCP tools; the display renders them at 60fps. The protocol is the API surface --- if an agent can describe it as JSON, Lux renders it.

The design follows Smalltalk's Morphic model: every visible element is a composable, nestable object. Windows contain tabs, tabs contain groups, groups contain buttons and plots. The long-term goal is a live environment where the MCP server is the message bus and Lux is the rendering layer, with the agent as the programmer at the keyboard.

**Platforms:** macOS, Linux

**Stage:** alpha (v0.0.0) --- protocol is stable, not yet published to PyPI

## Quick Start

```bash
uv pip install -e .        # Install from source
lux display &              # Start the display server
lux serve                  # Start the MCP server (stdio)
```

<details>
<summary>Run a demo</summary>

```bash
lux display &
uv run python demos/dashboard.py
```

Demos are in `demos/` --- each connects as a client and drives the display:

| Demo | What it shows |
|------|--------------|
| `interactive.py` | Sliders, checkboxes, combos, text inputs, color pickers |
| `containers.py` | Windows, tab bars, collapsing headers, groups |
| `dashboard.py` | Multi-window layout with draw canvases and live controls |
| `data_viz.py` | Tables, plots, progress bars, spinners, markdown |
| `menu_bar.py` | Custom menus, event handling, periodic refresh |

</details>

## Features

- **22 element kinds** --- text, buttons, images, sliders, checkboxes, combos, inputs, radios, color pickers, selectables, trees, tables, plots, progress bars, spinners, markdown, draw canvases, groups, tab bars, collapsing headers, windows, separators
- **Layout nesting** --- windows contain tab bars contain groups contain any element, arbitrarily deep
- **Incremental updates** --- `update` patches individual elements by ID without replacing the scene
- **Menu bar** --- built-in Lux/Theme/Window menus, plus agent-extensible custom menus via `set_menu`
- **Interaction events** --- button clicks, slider changes, menu selections queue as events the agent reads via `recv`
- **Auto-spawn** --- `LuxClient` starts the display server on first connection if it isn't running
- **Unix socket IPC** --- length-prefixed JSON frames, no HTTP overhead, no threads

## MCP Tools

Agents interact with Lux through six MCP tools exposed by `lux serve`:

| Tool | What it does |
|------|-------------|
| `show(scene_id, elements)` | Replace the display with a new element tree |
| `update(scene_id, patches)` | Patch elements by ID (set fields or remove) |
| `set_menu(menus)` | Add custom menus to the menu bar |
| `clear()` | Remove all content from the display |
| `ping()` | Round-trip latency check |
| `recv(timeout)` | Read the next interaction event (clicks, changes) |

## What It Looks Like

### Show text and a button

```json
{"tool": "show", "input": {
  "scene_id": "hello",
  "elements": [
    {"kind": "text", "id": "t1", "content": "Hello from the agent"},
    {"kind": "button", "id": "b1", "label": "Click me"}
  ]
}}
```

Returns `"ack:hello"`. When the user clicks the button:

```json
{"tool": "recv", "input": {"timeout": 5.0}}
```

Returns `"interaction:element=b1,action=click,value=True"`.

### Multi-window dashboard

```json
{"tool": "show", "input": {
  "scene_id": "dash",
  "elements": [
    {"kind": "window", "id": "w1", "title": "Controls", "x": 10, "y": 10,
     "children": [
       {"kind": "slider", "id": "vol", "label": "Volume", "value": 50}
     ]},
    {"kind": "window", "id": "w2", "title": "Chart", "x": 320, "y": 10,
     "children": [
       {"kind": "plot", "id": "p1", "title": "Trend",
        "series": [{"label": "y", "type": "line",
          "x": [1,2,3,4], "y": [10,20,15,25]}]}
     ]}
  ]
}}
```

### Update a single element

```json
{"tool": "update", "input": {
  "scene_id": "dash",
  "patches": [
    {"id": "vol", "set": {"value": 75}}
  ]
}}
```

## Element Kinds

| Category | Kinds |
|----------|-------|
| Display | `text`, `button`, `image`, `separator` |
| Interactive | `slider`, `checkbox`, `combo`, `input_text`, `radio`, `color_picker` |
| Lists | `selectable`, `tree` |
| Data | `table`, `plot`, `progress`, `spinner`, `markdown` |
| Canvas | `draw` (line, rect, circle, triangle, polyline, text, bezier) |
| Layout | `group`, `tab_bar`, `collapsing_header`, `window` |

All elements with an `id` support an optional `tooltip` field (string shown on hover).

## CLI Commands

| Command | What it does |
|---------|-------------|
| `lux display` | Start the display server (ImGui window) |
| `lux serve` | Start the MCP server (stdio transport) |
| `lux status` | Check if the display server is running |
| `lux version` | Print version |

## Architecture

```text
Agent (Claude Code)
  │ MCP (stdio)
  ▼
lux serve (FastMCP)
  │ Unix socket (JSON frames)
  ▼
lux display (ImGui + OpenGL)
  │ renders at 60fps
  ▼
Window on screen
```

The display server and MCP server are separate processes. The MCP server is a thin adapter that translates MCP tool calls into protocol messages sent over the Unix socket. The display server runs the ImGui render loop, polls the socket each frame via `select()` with zero timeout, and renders whatever scene the agent last sent.

Client code can also use `LuxClient` directly as a Python library, bypassing MCP. The demos do this.

## Development

```bash
uv sync                        # Install dependencies
uv run ruff check .            # Lint
uv run ruff format --check .   # Check formatting
uv run mypy src/ tests/        # Type check (mypy)
uv run pyright                 # Type check (pyright)
uv run pytest                  # Test
```

## License

MIT
