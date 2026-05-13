# Lux

Part of [Punt Labs](https://github.com/punt-labs). This repo must be checked out inside the `punt-labs/` workspace meta-repo so that org-wide configuration loads via Claude Code's ancestor directory walk:

- **`punt-labs/CLAUDE.md`** — org workflow, delegation model, beads issue tracking, tool configuration
- **`punt-labs/.claude/rules/python-*.md`** — 19 Python OO coding rules, scoped via `paths:` frontmatter (load on-demand when `.py` files are touched)
- **`punt-labs/.envrc`** — git identity, beads DB connection, API keys from platform keychain
- **`punt-kit/standards/`** — canonical reference docs

If cloned outside the workspace, these rules and configuration will not be present.

**OO Python standards adopted 2026-05-13.** The codebase does not yet fully comply. Every commit must improve OO scores (`make check-oo`), never regress. Do not match existing code patterns that violate the rules — write new code to the standard and improve touched files incrementally.

Lux is a **visual output surface for Claude Code**. Vox gives agents a voice; Lux gives agents a screen. An ImGui window renders JSON element trees sent by agents over Unix socket IPC.

- **Package**: `punt-lux`
- **CLI**: `lux`, `luxd`
- **MCP server**: via `mcp-proxy` → `luxd` WebSocket
- **Python**: 3.13+, managed with `uv`

## Architecture

### How rendering works

An agent calls an MCP tool (e.g., `show_table()`, `show_dashboard()`). The MCP server (`server.py`) builds a JSON element tree describing the scene and sends it to `luxd` over WebSocket. `luxd` stores the scene and pushes it to `lux-display` over Unix socket IPC. The ImGui renderer draws the scene every frame at 60fps. This is immediate mode "cached" — the agent sends state once, the display re-renders each frame without further communication. Filters, search, and row selection run entirely in the display process with zero MCP round-trips.

### Key architectural boundary: protocol vs. rendering

The **JSON protocol** (`protocol.py`) is the API surface. Agents describe what they want as a tree of typed elements — tables, text, plots, groups, buttons, sliders, etc. The **rendering layer** (`display.py`) consumes the protocol and paints ImGui widgets. Changes to the protocol are contract changes — every consumer (agents, tests, the display) depends on them. Changes to rendering are implementation — they affect only the display process.

This separation means: protocol bugs break agents. Rendering bugs break the display. They overlap only when a new element kind is added (protocol + rendering in a single coordinated change).

### Three-tier distributed architecture

- **`lux-display`** — ImGui renderer. Receives JSON scene via Unix socket, renders every frame. Native dependencies (`imgui-bundle`, `numpy`, `Pillow`) live here behind the `[display]` optional extra.
- **`luxd`** — WebSocket session hub. Multiplexes MCP sessions, routes scene updates to the display, stores persistent state (scenes, menus, themes, client registrations).
- **`mcp-proxy`** — Transport bridge. Claude Code stdio ↔ luxd WebSocket. See `../mcp-proxy/`.

This is a proposal (`docs/architecture-x11-model.md`). The current implementation has the display and hub in one process. The three-tier split is the target architecture for v1 completion.

### Key modules

| Module | Responsibility |
|--------|---------------|
| `display.py` | ImGui rendering — **4,200 lines, known debt, must decompose** |
| `protocol.py` | JSON element types and serialization — **73 module-level functions, must migrate to methods** |
| `scene.py` | Scene state management: create, update, composite |
| `server.py` | FastMCP tool surface: `show`, `update`, `clear`, `show_table`, `show_dashboard`, etc. |
| `client.py` | Unix socket client for display ↔ hub communication |
| `applet.py` | Self-hosted display widget for embedding in other apps |

24 element kinds covering ImGui's core primitives. Primary consumers: beads issue browser (`show_table()`), dashboards (`show_dashboard()`), architecture diagrams (`show_diagram()`).

See `docs/architecture.tex` for the full current system description.

### Vision

**v1 (current):** A display canvas for Claude Code agents — tables, data, dashboards. The protocol is the API surface — agents describe JSON, Lux renders it.

**v2 (future):** A Pharo-inspired live environment where MCP is the message bus and Lux is the Morphic rendering layer. Agent introspects and reshapes UI at runtime. System browser, inspector, workspace.

**Guiding constraint:** do not add v2 features in v1. Hone the data-display core. Every element kind must justify itself by current agent usage, not by v2 composability.

## Code Quality

**`display.py` (4,200 lines) must be decomposed before new features are added to it.** Any PR that adds rendering logic to display.py without extracting existing code will be rejected. This is the single most important code quality constraint in this project — the file is too large to test effectively, too large to reason about, and every change to it risks regressions elsewhere in the renderer.

**`protocol.py` serialization** — 73 module-level functions that should be methods on protocol dataclasses. Replace with method-based serialization when touching this file. The current layer is a parallel set of functions that duplicates the protocol type hierarchy — a textbook violation of the OO principle that data and behavior belong together.

**MCP tool boilerplate** — 29 MCP tools in `server.py` with identical boilerplate. This signals a missing abstraction. Extract the pattern into a decorator or registry.

**OO ratchet:** `make check-oo` (part of `make check`) compares current OO scores against `.oo-baseline.json`. It passes only if no metric regressed on touched files and at least one metric improved. It fails if any metric got worse or nothing improved.

Workflow:
1. Write code that improves OO quality on the files you touch.
2. `make check` runs `check-oo --check` automatically. If it fails, fix the regression.
3. After all checks pass, run `make update-oo` to write the new baseline.
4. Stage `.oo-baseline.json` and `.oo-audit.jsonl` with your commit — they are committed files.

Bootstrap (first time only): run `make update-oo` to create the initial baseline.

- `make check-oo` — OO ratchet against baseline.
- `make update-oo` — update baseline and append to audit log after improvements.
- `make report` — full diagnostics including per-file OO breakdown.
- `make metrics` — ABC complexity analysis. `display.py` is at magnitude 1,795.
- `make coverage` — test coverage HTML report.

**Makefile note:** `make check` uses `uv run --extra display` for all targets. pyright runs via `npx pyright` (not `uv run pyright`) because the display extras pull native dependencies that confuse uv's pyright wrapper.

## Testing

### Pyramid

| Layer | Make target | Runs in CI | What it covers |
|-------|-------------|------------|----------------|
| Unit | `make test` | yes | Protocol types, serialization, scene management, element builders, client |
| Visual | manual | no | ImGui rendering correctness (requires display server running) |

### What good testing means in this project

Lux's biggest testing gap is the rendering layer. `display.py` is 4,200 lines with no automated visual regression tests — correctness is verified manually by looking at the display. This means:

- **Protocol tests are the primary safety net.** Every element kind must have tests that verify serialization roundtrips (build → serialize → deserialize → compare). Protocol changes without tests are unshippable.
- **Scene tests verify composition.** Multiple elements in a scene, tab switching, window management, detail panels — these must be tested at the scene level even though visual rendering is manual.
- **Decomposing display.py is prerequisite for meaningful render tests.** Until the 4,200-line file is split into testable units, the rendering layer remains undertested. Every change to display.py that includes extraction improves the testability of the codebase.

### Key relationships

- **Vox** (`../vox/`) — audio counterpart; follows the same plugin/release patterns
- **claude-plugins** (`../claude-plugins/`) — marketplace catalog entry

## Ethos & Delegation

Identity: `agent: claude` per `.punt-labs/ethos.yaml`. All code delegation uses ethos missions. Every non-trivial delegation has two phases: (1) **design mission** — describes problem, constraints, and invariants but does NOT prescribe a write set; (2) **implementation mission** — uses the write set produced by the design phase. The design mission's output IS the write set — the specialist decides what to create, split, or extract.

The COO must not read implementation files before writing the design spec. "Add a handler to display.py at line 923" is a predetermined write set that prevents the specialist from making design decisions. "Add a query operation that returns display metadata — the codebase has a generic query infrastructure, the implementation must follow code quality standards" gives the specialist latitude to decompose and restructure. This is how `display.py` grew to 4,200 lines — write sets were predetermined to existing files instead of letting the specialist extract.

### Why these pairings

Lux spans two domains that require distinct expertise: (1) **visual/UX** — element design, layout, theming, composability — owned by `edt` (information design) and `dna` (interaction design), with `kpz` for GPU/performance; (2) **protocol/infrastructure** — JSON element types, Unix-socket IPC, scene management, MCP tool surface — owned by `rmh`/`gvr` for Python, `mdm` for CLI, `djb` for IPC trust boundary. The protocol is the contract between these domains — changes to it require a worker from one domain and an evaluator from the other.

| Task type | Worker | Evaluator |
|-----------|--------|-----------|
| New element kind / protocol extension | `edt` (Tufte) | `dna` (Norman) |
| Visual / layout / theming change | `dna` | `edt` |
| Python implementation (rendering, IPC, scenes) | `rmh` (Hettinger) | `gvr` (van Rossum) |
| Protocol amendment (JSON patch, Unix-socket schema) | `gvr` | `rmh` |
| CLI surface (`lux …` commands, plugin shell) | `mdm` (McIlroy) | `rop` (Pike) |
| MCP tool surface (`show`, `update`, `clear`, etc.) | `mdm` | `rmh` |
| GPU / perf-sensitive rendering paths | `kpz` (Karpathy) | `rmh` |
| Security review (socket auth, IPC trust boundary) | `djb` (Bernstein) | `rmh` |
| Release / packaging / hybrid plugin pipeline | `adb` (Lovelace) | `mdm` |
| Frame-rate / latency budget verification | `kpz` | `edt` |

### Pipeline selection

Use `standard` pipeline for new elements, protocol changes, or any work touching the JSON wire format. Use `quick` for bugfixes inside an existing element that don't change the protocol. Review-cycle fix rounds use bare `Agent()`, not missions. Treat the JSON protocol as the API surface — any change demands an evaluator distinct from the worker.

## Release

Use `/punt:auto release [version=X.Y.Z]`. Lux is a CLI + Plugin Hybrid — releases publish to both PyPI (`punt-lux`) and the marketplace. Dev plugin testing: `claude --plugin-dir .` loads `lux-dev` alongside prod.

Release scripts: `scripts/release-plugin.sh` (swap `lux-dev` → `lux`), `scripts/restore-dev-plugin.sh` (restore dev state after tag).

**Gotcha from v0.5.0:** `.gitignore` must cover all transient files (`.coverage`, `*.ini`, `demos/`, `__pycache__/`, LaTeX artifacts) — `punt release` checks for a clean working tree.

## Key Documents

- `DESIGN.md` — ADR log
- `prfaq.tex` → `prfaq.pdf` — product direction
- `docs/architecture.tex` → `docs/architecture.pdf` — current system architecture
- `docs/architecture-x11-model.md` — three-tier distributed architecture proposal
