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
| module_size | 1,212 | ≤300 | FAIL — server.py, element_renderer, elements.py |
| classes_per_module | 27 | ≤3 | FAIL — protocol/elements.py (27 dataclasses) |
| class_to_func_ratio | 0.60 | ≥0.5 | PASS |
| init_violations | 0 | ==0 | PASS |
| public_attr_violations | 0 | ==0 | PASS |
| future_annotations | 1 | ==1 | PASS |

7 of 11 passing. 4 failing: method_ratio, max_complexity, module_size, classes_per_module.

## What's been shipped (11 PRs)

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

## What's left (all tasks now tracked as beads — see bd list --label=repo:lux)

New since PR #162: scene/manager.py CC=13 (worsened), hub.py/show.py/tools/* method_ratio 0.0.
Three-layer type model work (DES-030) added: lux-ayeh (epic), lux-5rk7 (scene graph nodes), lux-6jw9 (typed patches).
luxd three-process split: lux-fv1b (epic).

## What's left (ordered)

### Level 2: Module OO Conversions (method_ratio blockers)

Each needs: design → peer review → implement → local review → PR.

| Task | File | Why |
|------|------|-----|
| Extract DoctorChecker | __main__.py (453 lines) | method_ratio 0.04 |
| Assess hooks.py | hooks.py (105 lines) | method_ratio 0.0 — may not need class |
| ToolState class | tools/connection.py | Encapsulate `_client`, `_client_lock` |
| Remove client.py shim + LuxClient alias | client.py, __init__.py | PL-PP-1, trivial |

### Level 3: Class Decomposition (module_size blockers)

Each needs: design review → implement → local review → PR.

| Task | File | Lines → target |
|------|------|---------------|
| Extract FrameRenderer | display/server.py | 1,212→~600 |
| Split element_renderer into 3 | display/element_renderer.py | 999→3×300 |
| Move module-level fns into class | display/table_renderer.py | method_ratio 0.6→1.0 |
| Split elements.py by domain | protocol/elements.py | 27 classes→3 files |
| ElementCodec registry | protocol/elements.py | Same pattern as MessageRegistry |
| Assess display_client.py | display_client.py | avg_params=6.5 on one method |

### Level 4: Method Decomposition (max_complexity blockers)

Each needs: Extract Method → verify CC ≤ 10 → local review → PR.

| Task | File | CC |
|------|------|----|
| Decompose _render_table | table_renderer.py | 19 |
| Decompose server.py CC=14 | display/server.py | 14 |
| Decompose element_renderer CC=13 | element_renderer.py | 13 (3 methods) |
| Decompose handle_framed_scene | scene/manager.py | 11 |

### Health Check

After every 3 PRs: `make report`, compare aggregates, assess design quality vs metric grinding. Present to CEO.

## Design Documents

- `.tmp/message-codec-design.md` — MessageRegistry design (implemented)
- `.tmp/message-codec-review.md` — Peer review of above
- `.tmp/module-architecture-design.md` — display/, scene/, tools/ packages (implemented)
- `.tmp/module-architecture-review.md` — Peer review of above

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
