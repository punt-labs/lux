# Migration Plan — Domain Model Across All Tiers

**Status:** ACTIVE
**Target:** `docs/architecture/domain-model.md` (the north star) and `docs/architecture/x11-model.md` (the topology)
**Method:** B-amended (see "Methods considered and rejected" below)
**Authority:** This is the executable plan. Mission YAMLs cite PRs from this document; specialist agents (`rmh`, `gvr`, `mdm`, `djb`, `adb`, `kpz`) execute PRs in the order below.

## Why this document exists

`oo-refactoring-plan.md` predates the domain-model north star. `resume.md`
tracks current state but does not encode the path forward. This document is
the single source of truth for **how** we get from where we are to the target
architecture, in **what order**, under **what verification discipline**.

It is written for the agents and sub-agents who will execute it. If you are
reading this to plan a PR, the rules in §"The Bar" are non-negotiable and the
PR sequence in §"Pipeline" is the authoritative order.

## The Bar — non-negotiable invariants

The operator has stated these are not subject to interpretation. Any PR that
violates one of these is rejected before review.

1. **The system stays running at every step.** No flag days. Each PR is
   independently shippable. Existing agents that call `show()` /
   `show_table()` / `show_dashboard()` continue to work without modification
   until the final cleanup PR.

2. **`make check` passes on every commit, not every PR.** The OO ratchet
   must improve or hold; the suppression ratchet must hold or decrease. A
   commit that fails `make check` is a broken commit.

3. **No suppressions to land a PR.** No `# noqa`, no `# type: ignore`, no
   `# pylint: disable`, no `--no-verify`, no editing `.oo-baseline.json` by
   hand. If a suppression is genuinely necessary (e.g., a third-party
   library with no stubs), it must be approved by the operator before the
   PR is opened.

4. **No backwards-compatibility shims that outlive their PR (PL-PP-1).**
   When the new path covers the old one, the old one is deleted in the
   same PR that completes the coverage — not "in a follow-up." Re-exports,
   tombstone comments, "deprecated" aliases are forbidden.

5. **No dead code waiting to be wired (PY-RF-2).** A new class with zero
   callers is a refactoring failure. Infrastructure PRs ship with the
   first consumer that proves the infrastructure works.

6. **Local verification per commit, ship per PR.** Within each PR:
   - `make check` runs after every commit.
   - `code-reviewer` and `silent-failure-hunter` agents run on the diff
     of each commit (or each logical step of commits).
   - `make snapshot-parity` (introduced in PR 0) runs as a CI gate from
     PR 1 onward.
   - Manual smoke test (`make install` + restart `luxd` + exercise the
     affected MCP tools) is run by the agent who owns the PR before the
     PR opens.

7. **The COO does not write code.** Every implementation PR is delegated
   through an ethos mission. Mission YAMLs cite PY-OO-1/2/5/7, PY-CC-5/6,
   PY-IC-1, PY-TS-6/8/14, PY-EH-1/8 verbatim in the first 20 lines, with
   one BEFORE/AFTER example. Worker and evaluator are distinct handles per
   the lux/CLAUDE.md pairing table.

8. **PR granularity ≠ verification granularity.** The verification unit is
   the local step (one transformation, locally reviewed, locally tested).
   The shipping unit is rollback coherence. A PR contains as many verified
   local steps as fit one rollback-coherent unit of work.

9. **No time estimates.** Plans speak in PR count and dependency order.
   Cadence is whatever the work allows.

## Pipeline

Eight PRs. Each row names the rollback-coherent unit, the OO ratchet
direction it moves, and the assigned worker/evaluator pairing.

### PR 0 — Characterization baseline

| Field | Value |
|-------|-------|
| **Goal** | Capture behavioral snapshots of every MCP tool response against current `main`. |
| **What lands** | `tests/characterization/snapshots/` with one snapshot per MCP tool input → response. `make snapshot-parity` target that replays them. CI workflow runs the parity check on every PR from this point forward. |
| **Why this PR exists** | Without an oracle, every subsequent PR is shipping blind. The snapshots are the safety net that lets us migrate aggressively in PRs 1-5. |
| **Ratchet effect** | None directly. Adds tests. |
| **Worker / Evaluator** | `rmh` / `gvr` (Python test infrastructure). |
| **Acceptance** | `make snapshot-parity` passes against `main`. CI workflow runs it on every PR. Snapshots cover every MCP tool listed in `tools/tools.py`. |

### PR 1 — Domain infrastructure (scoped to basics)

| Field | Value |
|-------|-------|
| **Goal** | Land just enough of the `domain/` package to carry the `basics` element family end-to-end through the new pipeline. |
| **What lands** | `domain/` package with: `ClientId`, `SceneId`, `ElementId` newtypes; `Element` Protocol; `Update` sum type (`AddElement`, `RemoveElement`, `SetProperty` — only what `basics` needs); `Event` sum type (`ElementAdded`, `ElementRemoved`, `ElementUpdated`); `Display` class with `connect_client`, `disconnect_client`, `add_scene`, `apply(client_id, update) -> Event \| Error`, `subscribe`, `snapshot`. Each existing `basics` element type (Text/Button/Separator/Image) is made to satisfy `Element` Protocol via tests. **`Text` is carried through end-to-end internally as proof** — a test exercises `Display.apply(AddElement(...Text...))`, `SetProperty(...Text...)`, `RemoveElement(...Text...)` and asserts events fire correctly. |
| **What does NOT land** | No public migration. `show()` and every MCP tool still routes through the old `SceneManager` path. The new `Display` has no production consumer yet. |
| **Why "scoped to basics"** | Extract from working code, not toward imagined code. Building the full domain vocabulary before any of it has rendered a pixel is the empty-infrastructure failure mode. The other Update / Event kinds appear in the PRs that first need them. |
| **Ratchet effect** | `method_ratio` improves (new classes with behavior). `module_size` neutral (new package, no growth in existing files). `class_to_func_ratio` improves. |
| **Worker / Evaluator** | `rmh` (Python implementation) / `gvr` (Python evaluation). Mission YAML cites PY-OO-1/5/7, PY-CC-5, PY-IC-1, PY-TS-6, PY-EH-1/8. |
| **Acceptance** | Tests demonstrate every existing `basics` element type satisfies `Element` Protocol. `Text` round-trips Add/SetProperty/Remove through `Display.apply`. Events fire. `make snapshot-parity` still passes (no production behavior changed). |

### PR 2 — basics family fully native

| Field | Value |
|-------|-------|
| **Goal** | Migrate `basics` (Text/Button/Separator/Image) to the new pipeline end-to-end. Delete the old path for these kinds. |
| **What lands** | Codec methods on `basics` element classes (delete module-level `_to_dict_text` etc.). `basics` elements are live (mutable, validated, emit events). Per-kind renderer classes for `basics`. Wire path: agents calling `show(...)` with `basics` elements route through the new `Display.apply(AddElement(...))`. **Old `SceneManager.handle_scene` code paths exercised by these kinds are deleted in this PR.** |
| **Why this shape** | First production migration. Proves the new infrastructure works under real load. Old paths for other families remain untouched — those families still route through the old `SceneManager`. |
| **Ratchet effect** | `method_ratio` rises (codec methods + live element methods + renderer methods). `module_size` falls on `element_renderer.py` (per-kind renderer classes extracted). |
| **Worker / Evaluator** | `rmh` / `gvr` for the protocol/domain layer; `edt` (information design) consulted on per-kind renderer shape. |
| **Acceptance** | `make snapshot-parity` passes (output for `basics` elements is byte-identical). Local smoke test: `set_display_mode(mode="y", repo=...)`, `show(...)` with a Text + Button + Image, observe correct rendering, click button, observe Interaction routed back. The old code path for these kinds is gone from the diff (verified by grep). |

### PR 3 — inputs family

| Field | Value |
|-------|-------|
| **Goal** | Migrate `inputs` family (Slider/Checkbox/Combo/InputText/Radio/ColorPicker) through the new pipeline. Delete the old path for these kinds. |
| **What lands** | Same shape as PR 2 for `inputs`. New Update / Event kinds added as needed (e.g., `WidgetValueChanged` event). Wire path migrated. |
| **Ratchet effect** | Continued `method_ratio` rise. `element_renderer.py` shrinks further. |
| **Worker / Evaluator** | `rmh` / `gvr`. `dna` (interaction design) consulted on Interaction → Update flow for input elements. |
| **Acceptance** | `make snapshot-parity` passes. Local smoke test: each input kind interactable; values reach the agent via `recv()`. |

### PR 4 — layout family

| Field | Value |
|-------|-------|
| **Goal** | Migrate `layout` family (Group/Window/TabBar/CollapsingHeader). Delete the old path. |
| **What lands** | `ReparentElement` and `ReplaceElement` Update kinds added (needed for container semantics). Cycle detection (PY-EH-1) enforced in `Display.apply`. `CycleError` event. Per-kind renderer classes for containers. |
| **Ratchet effect** | Composite pattern fully realized. `Display` enforces structural invariants 4 and 5 from `domain-model.md`. |
| **Worker / Evaluator** | `rmh` / `gvr`. `rej` consulted on Composite pattern realization. |
| **Acceptance** | `make snapshot-parity` passes. Local smoke test: nested groups, tabbed scenes, collapsing sections all render and update correctly. Reparent test: move a Button from one Group to another via `ReparentElement`, observe event, verify the renderer reflects the new parent. |

### PR 5 — graphics + table + plot families

| Field | Value |
|-------|-------|
| **Goal** | Migrate the remaining element families. Complete the Event vocabulary. |
| **What lands** | `graphics` (Draw with all draw commands), `table` (TableElement with columns/rows/filters/detail), `plot` (PlotElement with series/axes). Complete `Event` vocabulary: `OwnershipError`, `DuplicateIdError`, `PropertyTypeError` (with full enforcement in `Display.apply`). `ClientConnected` / `ClientDisconnected` events emitted. Disconnection cascade implemented per invariant 7. |
| **Ratchet effect** | All 24 element kinds now native. `method_ratio` near or at target ≥ 0.80. `element_renderer.py` decomposed (each family in its own module, per-kind renderer classes). |
| **Worker / Evaluator** | `rmh` / `gvr` for protocol; `kpz` (ML/perf) consulted on plot rendering perf-critical paths; `edt` on table/plot information design. |
| **Acceptance** | `make snapshot-parity` passes. Local smoke test: draw a diagram with Draw commands, render a filterable table with detail panel, render a plot with multiple series. Cycle test, ownership test, duplicate-id test all raise the correct Event type and refuse the Update. |

### PR 6 — cleanup

| Field | Value |
|-------|-------|
| **Goal** | Delete every remaining old-path code. The hub becomes purely `Display.apply` routing. |
| **What lands** | `SceneMessage` whole-scene wire path deleted. `SceneManager.handle_scene` deleted. The `_RENDERERS` dispatch dict in `element_renderer.py` deleted (every kind has its own renderer class). Module-level `_to_dict` / `_from_dict` codec functions deleted (every type owns its own). Any tombstone comments, re-exports, deprecation shims removed. |
| **Ratchet effect** | `method_ratio` definitively ≥ 0.80. `module_size` for the major files (`server.py`, `element_renderer.py`) at or below 300. `classes_per_module` ≤ 3 throughout. |
| **Worker / Evaluator** | `rmh` / `gvr`. `djb` (security) consulted on the audit of removed code paths to confirm no input-validation logic is lost in the deletion. |
| **Acceptance** | `make snapshot-parity` passes. Local smoke test: full MCP surface exercised. OO ratchet shows targets met. Zero dead code remains. |

### PR 7 — process split

| Field | Value |
|-------|-------|
| **Goal** | Realize the x11-model topology — `lux-display` runs as a separate process from `luxd`, with `JsonCodec` as the port between them. |
| **What lands** | Two `Display` instances: `hub_display` in `luxd` (authoritative writer) and `wire_display` in `lux-display` (read-only mirror, drives the ImGui renderer). `JsonCodec` serializes Updates and Events across the Unix socket. Hub forwards Events to display; display forwards Interactions back. Both sides hold the same `Display` class — the only difference is the codec at the boundary. Process management updates (launchd / systemd integration for `lux-display`). |
| **Ratchet effect** | Architectural. `Display` class is exercised in both single-process (tests) and multi-process (production) modes — proves the operator's invariant that "objects and message passing become trivially equal to IPC calls." |
| **Worker / Evaluator** | `adb` (infra) / `mdm` (process model). `djb` reviews the IPC trust boundary. |
| **Acceptance** | `lux-display` runs as a child of `luxd` (or independently). Existing MCP surface continues to work. Tests can run both displays in one process (single-runtime requirement from `domain-model.md` §"Testability"). `make snapshot-parity` passes. Local smoke test: kill `lux-display`, `luxd` re-spawns it, scenes are recoverable from `hub_display`'s state. |

## Verification discipline

Every PR follows this loop. The loop is the contract.

1. **Read this document, the relevant ADRs in `DESIGN.md`, and
   `domain-model.md` / `x11-model.md`.**
2. **Author a mission YAML** that cites the OO rules in the first 20 lines
   with one BEFORE/AFTER example. The YAML lives at
   `.tmp/missions/<pr-name>.yaml`.
3. **Dispatch with `ethos mission create --file <yaml>`** then **`Agent(subagent_type=<worker>, run_in_background=true)`** — both steps are required. Verify the worker is running via TaskList before considering the mission active.
4. **The worker commits incrementally.** Each commit:
   - Is one logical step.
   - Passes `make check`.
   - Is locally reviewed by `code-reviewer` and `silent-failure-hunter`
     agents before the next commit lands.
   - Is locally smoke-tested if it touches anything user-visible.
   - Does not accumulate more than 30 minutes of uncommitted changes.
5. **After all commits are in:** `make snapshot-parity` runs end-to-end.
   Manual smoke test of the affected MCP tools by the COO before push.
6. **PR opens.** Copilot review requested once. Polling loop monitors CI.
7. **Address every comment.** No suppressions. No "this is fine."
8. **Resolve threads, merge, delete branch, pull main.** Inner loop done.

## Test pyramid for the migration

| Tier | Where | What it covers |
|------|-------|----------------|
| **Characterization (PR 0)** | `tests/characterization/snapshots/` | Every MCP tool input → response captured on `main`. Replayed in CI on every PR. Catches output-level regressions. |
| **Domain unit (PR 1 onward)** | `tests/domain/` | `Display.apply(client, update)` returns the expected Event or Error. Ownership, cycle, type, duplicate-id invariants enforced. Single-runtime tests per `domain-model.md` §"Testability" — no GUI, no socket, no process boundary. |
| **Family integration (PR 2-5)** | `tests/integration/families/<family>/` | End-to-end exercise of one element family through the new pipeline. Renders headlessly via the introspection API; verifies the scene snapshot matches the expected tree shape. |
| **Manual smoke (every PR)** | Run by the agent | `make install` + restart `luxd` + exercise the changed MCP tools in a real Claude Code session. Paste the actual output in the PR description. |

## Methods considered and rejected

For the record: three migration methods were evaluated by three architect
reviewers (`rej` Smalltalk/refactoring school, `kwb` TDD/XP school, `rop`
Plan 9 simplicity school). Verdicts:

| Method | Description | Verdict | Reason |
|--------|-------------|---------|--------|
| **A — Horizontal Bands** | One architectural concept per PR across the whole codebase. ~7 PRs, each cross-cutting. | ITERATE (3/3) | PR 6 in this method ("all 24 kinds migrated and old paths deleted in one PR") is a flag day. Empty infrastructure (PR 2) ships before any consumer. Shadow Display tax has no production value. If PR 6 is split family-by-family, A collapses into B — not chosen because B captures the same end state without the intermediate cost. |
| **B — End-to-End Vertical Slices (amended)** | Infrastructure scoped to first family + family-by-family migration with each PR deleting its own old path. ~8 PRs total. | **SELECTED** | Each PR is a rollback-coherent unit. Two vocabularies never coexist for the same noun longer than one PR. Snapshot parity from PR 0 is the safety net. Adopted as the active plan. |
| **C — Parallel Universe Cutover** | Build a complete second implementation under `domain/`. Cut over with a one-line-per-tool flip. Delete old code. 3 PRs. | REJECTED (3/3 REJECT) | The canonical big-bang rewrite pattern. PR 1 has no production consumer until the flip; the flip surfaces every assumption error simultaneously. Snapshot parity proves outputs match but not behavior (event ordering, error timing, interaction semantics aren't captured). |

The architectural target (the `domain-model.md` north star) is **not under
review**. The reviewers were scoped to migration method only. The decision
to pursue the domain model across all tiers is recorded in DES-031.

## Open work tracker

Track via `bd` in the `repo:lux` label. Each PR is a bead with
dependency edges to the previous PR's bead. Do not work two PRs in
parallel on the same working tree.

## References

- `docs/architecture/domain-model.md` — the algebra this plan realizes
- `docs/architecture/x11-model.md` — the topology PR 7 splits into
- `docs/architecture/introspection-api.md` — already-implemented query pattern; family integration tests use it
- `docs/oo-refactor/resume.md` — current OO scores; will be updated after each PR
- `DESIGN.md` DES-030 — three-layer type model (wire / scene graph / snapshot)
- `DESIGN.md` DES-031 — Domain Model Across All Tiers (this plan's grounding decision)
- `punt-labs/.claude/rules/python-*.md` — the rules every mission YAML cites
