# Lux

**OO Python standards adopted 2026-05-13.** The codebase does not yet fully comply. Rules in `../.claude/rules/python-*.md` are the target. Every commit must improve OO scores (`make check-oo`), never regress. Do not match existing code patterns that violate the rules — write new code to the standard and improve touched files incrementally.

Visual output surface for Claude Code. Vox gives agents a voice; Lux gives agents a screen. An ImGui window renders JSON element trees sent by agents over Unix socket IPC.

- **Package**: `punt-lux`
- **CLI**: `lux`, `luxd`
- **MCP server**: via `mcp-proxy` → `luxd` WebSocket
- **Python**: 3.13+, managed with `uv`

## Architecture

Three-tier distributed architecture:

- **`lux-display`** — ImGui renderer. Receives JSON scene via Unix socket, renders every frame. Immediate mode "cached" — the agent sends state once, the display re-renders each frame without further communication.
- **`luxd`** — WebSocket session hub. Multiplexes MCP sessions, routes scene updates to the display process. Persistent state: scenes, menus, themes, client registrations.
- **`mcp-proxy`** — Transport bridge. Claude Code stdio ↔ luxd WebSocket. See `../mcp-proxy/`.

24 element kinds covering ImGui's core primitives (tables, text, plots, groups, buttons, sliders, color pickers, radio groups, input fields, etc.). Primary consumer: beads issue browser (`show_table()`), dashboards (`show_dashboard()`), architecture diagrams (`show_diagram()`).

Key modules: `display.py` (ImGui rendering — known oversized, see Known Quirks), `protocol.py` (JSON element types and serialization), `scene.py` (scene state management), `server.py` (FastMCP tool surface), `client.py` (Unix socket client), `applet.py` (self-hosted display widget).

**v1 focus**: tables, data, dashboards. The protocol is the API surface — agents describe JSON, Lux renders it. **v2 (future)**: Pharo-inspired live environment where MCP is the message bus and Lux is the Morphic rendering layer. Do not add v2 features in v1.

See `docs/architecture.tex` for the full specification.

## Testing

### Pyramid

| Layer | Make target | Runs in CI | What it covers |
|-------|-------------|------------|----------------|
| Unit | `make test` | yes | Protocol types, serialization, scene management, element builders, client |
| Visual | manual | no | ImGui rendering correctness (requires display server running) |

`make check` requires `--extra display` (handled by Makefile). `make metrics` for ABC complexity. `make coverage` for test coverage with HTML report.

### Known testing gaps

- No automated visual regression tests — element rendering correctness is verified manually.
- `display.py` is too large to test effectively — decomposition is prerequisite for meaningful unit test coverage of the rendering layer.

## Ethos & Delegation

Identity: `agent: claude` per `.punt-labs/ethos.yaml`. All code delegation uses ethos missions. Every non-trivial delegation has two phases: (1) **design mission** — describes problem, constraints, and invariants but does NOT prescribe a write set; (2) **implementation mission** — uses the write set produced by the design phase. The design mission's output IS the write set — the specialist decides what to create, split, or extract. This is critical: prescribing a write set before design prevents refactoring and forces code into existing modules.

Use `standard` pipeline for new elements, protocol changes, or any work touching the JSON wire format. Use `quick` only for bugfixes inside an existing element. Review-cycle fix rounds (Copilot/Bugbot findings) use bare `Agent()`, not missions. Treat the JSON protocol as the API surface — any change there demands an evaluator distinct from the worker.

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

## Release

Use `/punt:auto release [version=X.Y.Z]`. Lux is a CLI + Plugin Hybrid — releases publish to both PyPI and the marketplace. Dev plugin testing: `claude --plugin-dir .` loads `lux-dev` alongside prod.

## Known Quirks

- **`display.py` (4,200 lines)** — must be decomposed before new features are added to it. Any PR that adds rendering logic to display.py without extracting existing code will be rejected.
- **`protocol.py` serialization** — 73 module-level functions that should be methods on protocol dataclasses. Replace with method-based serialization when touching this file.
- pyright runs via `npx pyright` (not `uv run pyright`) because the display extras pull native dependencies that confuse uv's pyright wrapper.
- `make check` uses `uv run --extra display` for all targets — the Makefile handles this.

## Key Documents

- `DESIGN.md` — ADR log
- `prfaq.tex` → `prfaq.pdf` — product direction
- `docs/architecture.tex` → `docs/architecture.pdf` — current system architecture
- `docs/architecture-x11-model.md` — three-tier distributed architecture proposal
