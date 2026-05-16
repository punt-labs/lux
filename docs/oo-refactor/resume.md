# OO Refactoring Resume

## Goal

Transform the Lux codebase from a procedural monolith to a well-factored OO design with domain-aligned packages, proper encapsulation, and low coupling. Work order: package → module → class → method.

## Current OO Scores (as of PR #165, 2026-05-16)

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| method_ratio | 0.68 | ≥0.80 | FAIL — procedural modules remain |
| encapsulation_ratio | 1.00 | ≥1.0 | PASS |
| avg_params | 0.98 | ≤4.0 | PASS |
| max_complexity | 19 | ≤10 | FAIL — table_renderer, server, element_renderer |
| avg_complexity | 2.31 | ≤5.0 | PASS |
| module_size | 1,213 | ≤300 | FAIL — server.py, element_renderer, elements.py |
| classes_per_module | 27 | ≤3 | FAIL — protocol/elements.py (27 dataclasses) |
| class_to_func_ratio | 0.60 | ≥0.5 | PASS |
| init_violations | 0 | ==0 | PASS |
| public_attr_violations | 0 | ==0 | PASS |
| future_annotations | 1 | ==1 | PASS |

7 of 11 passing. 4 failing: method_ratio, max_complexity, module_size, classes_per_module.

## What's been shipped (15 PRs)

| PR | What | Key result |
|----|------|-----------|
| #148 | Pre-flight: __new__, encapsulation, types.py | Fixed foundations |
| #150 | Phase 1: protocol/ package | protocol.py → 3 files |
| #151 | Phase 2a: 4 classes from display.py | SceneManager, SocketServer, TableRenderer, QueryDispatcher |
| #152 | Phase 2b: ElementRenderer + MenuManager | display.py 4,257→1,647 |
| #155 | Phases 3–4: _query_tool + display_client cleanup | -137 lines |
| #156 | Phase 5 partial: ServiceManager, SessionHub, BeadsBrowser | service.py 347→94 |
| #157 | MessageRegistry | max_complexity 30→4 |
| #158 | display/ package | Rendering subsystem grouped |
| #159 | scene/ package | Scene graph domain grouped |
| #160 | tools/ package + coupling tool | 3-way split + oo_coupling.py |
| #161 | Foundation OO: ConfigManager, DisplayPaths, ProxyConfigFile | 3 procedural modules → classes |
| #162 | Dead code removal + BeadsBrowser wrappers + suppression ratchet | 110 baseline |
| #163 | OO resume document added at repo root | Context only |
| #164 | Protocol dataclasses frozen=True+slots=True; hasattr/setattr → dataclasses.replace(); docs/ reorganized; DES-029, DES-030; tests/CLAUDE.md; make test-integration/test-e2e | Wire types correct; three-layer model documented |
| #165 | luxd registered as launchd service; CLAUDE.md notes hub restart after install | Operational fix |

## What's left

All remaining work is tracked as beads (`bd list --label=repo:lux`). Tables below are the canonical reference.

### OO Level 2 — method_ratio blockers

Each needs: design → peer review → implement → local review → PR.

| Bead | Task | Files | Notes |
|------|------|-------|-------|
| lux-136o | Extract DoctorChecker class | `__main__.py` (457 lines, method_ratio 0.04) | Doctor subcommand logic → class with check methods |
| lux-9k38 | Fix method_ratio 0.0 modules | `hooks.py`, `show.py`, `hub.py`, `tools/server.py`, `tools/connection.py`, `display/idle_screen.py` | All procedural — assess each, convert to class-based. idle_screen.py also has avg_params=6.5. |
| lux-3bp8 | Remove client.py shim | `client.py`, `__init__.py` | PL-PP-1 violation, trivial (chore) |

### OO Level 3 — module_size blockers

Each needs: design → two-pass implementation → local review → PR.

| Bead | Task | File | Size → Target |
|------|------|------|--------------|
| lux-gcgf | Extract FrameRenderer | `display/server.py` | 1,213 → ~600 |
| lux-wzpq | Split into domain renderers | `display/element_renderer.py` | 999 → 3×300 |
| lux-jyj2 | Promote fns into class | `display/table_renderer.py` | 540, method_ratio 0.61 → 1.0 |
| lux-9i26 | Split by element domain | `protocol/elements.py` | 1,013, 27 classes → 4 files. Fixes module_size and method_ratio; classes_per_module (≤3) still requires most classes to be further decomposed — note as ongoing. |
| lux-skc7 | Split by message domain | `protocol/messages.py` | 570, 22 classes. Mirrors lux-9i26. |
| lux-n5ep | ElementCodec registry | `protocol/elements.py` | Blocked by lux-9i26 |
| lux-r77f | Typed tool handler classes | `tools/tools.py` | 656, method_ratio 0.0 |
| lux-5v5f | Assess and decompose | `display/menu_manager.py` | 507 |
| lux-40xx | Assess: module_size + avg_params | `display_client.py` | 541 |
| — | CC=13 work (lux-7bpg) also reduces | `scene/manager.py` | 395 — no separate bead; improves as CC work proceeds |

### OO Level 4 — max_complexity blockers

Each needs: Extract Method → verify CC ≤ 10 → local review → PR.

| Bead | Task | File | CC |
|------|------|------|----|
| lux-7bpg | Decompose _render_table | `display/table_renderer.py` | 19 |
| lux-7bpg | Decompose _on_frame/_handle_message | `display/server.py` | 14 |
| lux-7bpg | Decompose _render_element | `display/element_renderer.py` | 13 |
| lux-7bpg | Decompose handle_framed_scene | `scene/manager.py` | 13 |

### Architecture — three-layer type model (DES-030)

| Bead | Task | Notes |
|------|------|-------|
| lux-q316 | Decision: DES-030 (PROPOSED) | Three-layer model: wire / scene graph / snapshot |
| lux-ayeh | Epic: three-layer implementation | Blocked by lux-q316 |
| lux-5rk7 | Scene graph nodes | Mutable per-element-kind classes with typed apply(); blocked by lux-ayeh |
| lux-6jw9 | Typed patches per element kind | Wire format change; blocked by lux-5rk7 |

### Architecture — luxd three-process split

| Bead | Task | Notes |
|------|------|-------|
| lux-fv1b | Epic: hub daemon + service + mcp-proxy | hub.py WebSocket server, session isolation, plugin.json integration. See `docs/architecture/x11-model.md` and `docs/architecture/luxd-impl.md`. |

### Health Check

After every 3 PRs: `make report`, compare aggregates. Present to CEO before continuing.

## Design Documents

- `docs/oo-refactor/dynamic-access-design.md` — three-layer type model, dynamic access debt, path forward
- `docs/architecture/x11-model.md` — X11 architecture, three-process model, update/refresh rate separation
- `docs/architecture/luxd-impl.md` — luxd hub implementation spec (Phase 1 target)
- `DESIGN.md` DES-029, DES-030 — ADRs for protocol frozen types and three-layer model

## How to Continue

1. __Order__: package → module → class → method. Don't skip levels.
2. __Delegate all code__: specialist agents (`rmh` for Python, `gvr` for protocol). COO writes specs and reviews.
3. __Sequential agents only__: never run parallel agents on the same working tree.
4. __Two-pass extraction__: for large files, create new file first, then wire callers in a second pass.
5. __Migration order for module conversions__: add class alongside existing functions → update callers one by one → delete old functions. System must be importable after every file write (hooks run `make check`).
6. __New files must meet OO standards__: no "pre-existing" excuse for moved code.
7. __Local review mandatory__: code-reviewer + silent-failure-hunter before every PR push.
8. __`make check` before every commit__: includes check-oo, check-suppressions, lint, type, test.
9. __Design review for non-trivial conversions__: design mission → peer review → present to CEO → implement.
10. __Reply to all biff messages__.

## Key Tools

- `make check` — single quality gate (OO + suppressions + lint + type + test)
- `make check-coupling` — coupling metrics (informational)
- `tools/oo_score.py` — OO metrics with ratchet (`--check`, `--update`, `--rebaseline`)
- `tools/oo_coupling.py` — coupling + cohesion metrics
- `tools/suppression_ratchet.py` — inline suppression count ratchet (110 baseline)

## Lessons Learned

- Parallel agents on shared working trees cause conflicts — always sequential
- Hooks revert files when `make check` fails mid-edit — migration must keep system importable after every write
- Sub-agents reliably create new files but often don't complete wiring — use two-pass extraction
- "Pre-existing" is never an excuse — extracted code in new files must meet current OO standards
- The OO ratchet has edge cases with renames and structural changes — use `--rebaseline` sparingly
- Design reviews (design → peer review → present) catch real issues — don't skip for "small" changes
