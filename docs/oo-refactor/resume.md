# OO Refactoring Resume

**As of:** PR #178 (2026-05-21)
**Prior:** through PR #165 (2026-05-16)

## Goal

Transform Lux from a procedural monolith to a well-factored OO design with
domain-aligned packages, proper encapsulation, and low coupling. Work order:
package → module → class → method.

Target state is named formally in `docs/architecture/domain-model.md`.

## Current OO scores

Aggregate of `python tools/oo_score.py src/punt_lux/`:

| Metric | Target | PR #165 | Current | Status |
|--------|--------|---------|---------|--------|
| `method_ratio` | ≥ 0.80 | 0.68 | **0.636** | **FAIL — went backwards.** Phase A added module-level `_to_dict` / `_from_dict` codec functions; PY-OO-7 names this anti-pattern. |
| `encapsulation_ratio` | == 1.0 | 1.00 | 1.00 | PASS |
| `avg_params` | ≤ 4.0 | 0.98 | 0.99 | PASS |
| `max_complexity` | ≤ 10 | 19 | **19** | **FAIL** — `table_renderer`, `server`, `element_renderer`. |
| `avg_complexity` | ≤ 5.0 | 2.31 | 2.07 | PASS |
| `module_size` | ≤ 300 | 1,213 | **1,203** | **FAIL** — `oo_score.py`'s metric is non-empty lines; the three biggest are `display/server.py` (1,203), `element_renderer.py` (~999), `__main__.py` (~488). Raw `wc -l` line counts for the same files are 1,370 / 1,130 / 576. |
| `classes_per_module` | ≤ 3 | 27 | **9** | **FAIL** — improved by Phase A, still over. |
| `class_to_func_ratio` | ≥ 0.5 | 0.60 | 0.62 | PASS |
| `init_violations` | == 0 | 0 | 0 | PASS |
| `public_attr_violations` | == 0 | 0 | 0 | PASS |
| `future_annotations` | == 1 | 1 | 1 | PASS |

**7 of 11 passing.** Same four failing metrics as PR #165, with `method_ratio`
actively worse and `classes_per_module` substantially improved.

## What shipped since PR #165

| PR | Bead | Summary |
|----|------|---------|
| #166–#167 | — | OO resume updates |
| #168 | — | Move dev deps to PEP 735 dependency-groups |
| **#169** | lux-9i26 | **Phase A part 1: `protocol/elements/` split (27 dataclasses → 6 modules)** |
| **#170** | lux-skc7 | **Phase A part 2: `protocol/messages/` split (22 dataclasses → 5 modules)** |
| #171 | lux-ckad | `bd ready` surfaces failures (silent-default bug fix) |
| **#172** | lux-n5ep | **`ElementCodec` registry consolidates per-kind dispatch** |
| #173 | lux-z9nh | Stop hiding lux-display from macOS Dock |
| #174 | — | CLAUDE.md OO rules non-negotiable |
| #175 | — | Session housekeeping (gitignore, submodule, design doc) |
| **#176** | lux-4n1b | **Typed `DrawCommand` decoder; remove silent `.get()` defaults from renderer** |
| #177 | — | Rename `*Cmd` records to nouns (they aren't commands) |
| **#178** | — | **`docs/architecture/domain-model.md` — north star** |

Three structural advances (#169, #170, #176) and one architectural foundation
doc (#178). The OO ratchet enforced direction of travel on every PR; the
absolute targets remain unmet.

## Open work from `oo-refactoring-plan.md`

| Step | Status | What's left |
|------|--------|-------------|
| **2.x** display.py decomposition | Partial | Classes extracted (TableRenderer, ElementRenderer, MenuManager, SceneManager, SocketServer, QueryDispatcher) but `display/server.py` is **still 1,370 lines** — Phase 2 was structural-split-only, not size-targeted. |
| **3.x** tools.py refactor | Partial | `_query_tool` decorator in place. `ToolState` class not done (was optional). |
| **4.1** Remove `inspect_scene` / `list_scenes` / `screenshot` and their queues | **Superseded** | `docs/architecture/introspection-api.md` (2026-05-12) reverses this — keep the three ops, generalise the pattern through a `QueryRequest` / `QueryResponse` envelope and a single dispatcher, grow to 15+ ops. Implementation of the introspection-api pattern is the live work item, not removal. |
| **5.2** `SessionHub` class in `hub.py` | **Open** | `hub.py` is 5 module-level functions, zero classes. |
| **5.3** `DoctorChecker` class in `__main__.py` | **Open** | `__main__.py` is 576 lines, 23 functions, zero classes. |
| Size targets | **Open** | None of the three largest modules meets the ≤ 300 `module_size` target. `oo_score.py` reports 1,203 / ~999 / ~488 for `display/server.py` / `element_renderer.py` / `__main__.py`; raw `wc -l` is 1,370 / 1,130 / 576. |
| `method_ratio` target | **Open** | Aggregate 0.636 vs target ≥ 0.80. Procedural codec functions in `protocol/elements/*.py` and `protocol/messages/*.py` are the largest contributor — same anti-pattern as the draw-command surface had before PR #176. |
| `max_complexity` target | **Open** | 19 vs target ≤ 10. Concentrated in three render-path methods. |

## Open work from `oo-class-design.md`

`oo-class-design.md` prescribes 13 classes. 11 exist; 2 don't:

| Class | File | Status |
|-------|------|--------|
| `SessionHub` | `hub.py` | **Not created** — `hub.py` is module-level functions only |
| `DoctorChecker` | `__main__.py` | **Not created** — `__main__.py` is module-level functions only |

## Open work from `domain-model.md`

| Stage | What it means | Status |
|-------|---------------|--------|
| 1 | Name the domain | **Done** — PR #178 |
| 2 | Extract `Display`, `Client`, `Update`, `Event` | Not started |
| 3 | Make Elements live (mutable, emit events on mutation) | Not started |
| 4 | Semantic updates on the wire | Not started |
| 5 | Decompose `element_renderer.py` | Not started |
| 6 | Split process boundary (hub / display server) | Not started |

## Architecture references

| Doc | What it answers |
|-----|-----------------|
| `docs/architecture/system.tex` | Comprehensive technical architecture (canonical) |
| `docs/architecture/domain-model.md` | What the code holds — Composite tree, Client, Update, Event, Port |
| `docs/architecture/x11-model.md` | Where the code runs — three-tier process model |
| `docs/architecture/luxd-impl.md` | How the hub is built — MCP proxy spec |
| `docs/architecture/introspection-api.md` | What introspection ops exist and how they dispatch |
| `docs/oo-refactor/oo-class-design.md` | Class-by-class OO design (2 classes still open) |
| `docs/oo-refactor/oo-refactoring-plan.md` | Executable refactoring plan (several steps open per above) |

## Next priorities, ordered

1. **`element_renderer.py` decomposition** — biggest single OO debt with no
   API change. Step toward `module_size` and `max_complexity` targets.
2. **Domain-model Stage 2-3** — introduce `Display`, `Client`, `Update`,
   `Event`. Largest architectural step; unlocks the rest of the north star.
3. **Implement `introspection-api.md` generic pattern** — `QueryRequest` /
   `QueryResponse` envelope + single `_handle_query` dispatcher in
   `display/server.py`. Migrates the existing three ops (`inspect_scene`,
   `list_scenes`, `screenshot`) to the pattern; opens the door to the other
   12+ ops the doc inventories.
4. **`hub.py` SessionHub** (Step 5.2) and **`__main__.py` DoctorChecker**
   (Step 5.3) — finish the Phase 5 punch list.
5. **`PlotElement.series`** — same anti-pattern as DrawElement had pre-#176;
   small win, proves PY-EH-8 / PY-TS-14 / PY-OO-7 at a second case.

## Standards rules introduced this cycle

Three rules added in workspace PR
[punt-labs/punt-labs#42](https://github.com/punt-labs/punt-labs/pull/42),
still pending merge:

- **PY-EH-8** — Raise, don't return `None`, on unrepresentable values.
- **PY-TS-14** — Every `T | None`, `Any`, `dict[str, Any]` annotation requires
  an inline justification comment.
- **PY-OO-7** — Module-level helpers next to a class are missing methods.

These describe the anti-patterns this cycle removed (silent-default
rendering, untyped wire dicts, procedural helpers). They will gate future PRs
in the same surfaces.

## How to continue

1. **Order**: package → module → class → method. Don't skip levels.
2. **Delegate all code**: specialist agents (`rmh` for Python, `gvr` for
   evaluation). COO writes specs and reviews.
3. **Sequential agents only**: never run parallel agents on the same
   working tree.
4. **Two-pass extraction**: for large files, create new file first, then
   wire callers in a second pass.
5. **New files must meet OO standards**: no "pre-existing" excuse for
   moved code.
6. **Local review mandatory**: `feature-dev:code-reviewer` and
   `pr-review-toolkit:silent-failure-hunter` before every PR push.
7. **`make check` before every commit**: includes `check-oo`,
   `check-suppressions`, lint, type, test.
8. **Cite the OO rules in mission YAML** for any protocol/data work:
   PY-OO-1/2/5, PY-CC-5/6, PY-IC-1, PY-TS-6/8, PY-EH-1/8, PY-OO-7, PY-TS-14.

## Key tools

- `make check` — single quality gate (OO + suppressions + lint + type + test)
- `make check-coupling` — coupling metrics (informational)
- `tools/oo_score.py` — OO metrics with ratchet (`--check`, `--update`, `--rebaseline`)
- `tools/oo_coupling.py` — coupling + cohesion metrics
- `tools/suppression_ratchet.py` — inline suppression count ratchet (108 current; 110 baseline)
