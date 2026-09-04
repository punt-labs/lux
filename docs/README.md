# Docs Guide

Use this file when the repo's documentation feels contradictory, or to find
the right document for a question. Every document under `docs/` is listed
here with its status.

Lux has documentation for:

- the current/intermediate implementation
- the target architecture
- coding standards
- formal models (Z specs with ProB model-checks and coverage audits)
- completed migrations and delivered designs (historical records)
- alternative concepts

These are not the same thing.

## Start Here

- [architecture/target/target.md](./architecture/target/target.md)
  Canonical target architecture for the rewrite.
- [architecture/system.tex](./architecture/system.tex)
  Current/intermediate architecture. This is the org-standard current-system
  document.

If the question is "what are we rewriting toward?", start with the target docs.
If the question is "what does the code approximately do today?", use
`system.tex`.

## Users and Integrators

- [library.md](./library.md) — the Python library guide: `LuxClient`,
  the persistent `LuxHubClient` listener, and connecting to `luxd`'s MCP
  endpoint directly. The [README](../README.md) is for users; this is the
  developer companion.

## Coding Standard

- [standards/python-oo.md](./standards/python-oo.md)

This is the repo-level implementation standard. It is where Lux's OO-only
policy and ratchet enforcement live. It is not an architecture document.

## Workflow

- [WORKFLOW.md](./WORKFLOW.md) — the three nested loops (backlog, PR,
  mission) every change in this repository runs through.

## Target Architecture

- [architecture/target/README.md](./architecture/target/README.md)
- [architecture/target/topology.md](./architecture/target/topology.md)
- [architecture/target/ui-model.md](./architecture/target/ui-model.md)
- [architecture/target/element-contract.md](./architecture/target/element-contract.md)
- [architecture/target/introspection-api.md](./architecture/target/introspection-api.md)
- [architecture/target/addressing.md](./architecture/target/addressing.md) —
  identity ladder and multi-Hub aggregation (DES-089)

These documents describe the intended Hub-authoritative architecture.

## Delivered Designs

Design documents whose work shipped. Each carries a status banner; they remain
the reference for how their subsystem is built.

- [architecture/one-code-path.md](./architecture/one-code-path.md) — the
  typed `Operations` facade, REST front door, thin adapters (epic `lux-7gcz`,
  v0.20.0/v0.21.0).
- [architecture/menu-capability-model.md](./architecture/menu-capability-model.md)
  — the session-and-callback menu model (operator-ruled 2026-07-29; the
  earlier "capability" abstraction it once proposed is withdrawn).
- [architecture/mcp-display-liveness.md](./architecture/mcp-display-liveness.md)
  — the Hub replicator: dirty-signal coalescing, bounded sends, reap/reconnect
  recovery. Modeled by `hub_replicator.tex` below.
- [architecture/e2e-harness-design.md](./architecture/e2e-harness-design.md)
  — the in-process end-to-end business-event loop harness (ships in
  `tests/e2e/`).
- [architecture/client-identity.md](./architecture/client-identity.md) — the
  diagnosis and ratified policy behind DES-057 (operator-ruled 2026-07-28:
  durable session-scene lifetime, `identify` + challenge, anonymous REST
  rejected); the shipped shape (PRs #290-#292) evolved past several of this
  document's specifics — DES-057 in `DESIGN.md` is authoritative for those.
- [architecture/scene-display-packaging-design.md](./architecture/scene-display-packaging-design.md)
  — the `scene/` → `display/replica/` dissolution and the N1/N2/N3 naming
  convention (operator-ratified 2026-08-08; PRs #318-#319).

## Deferred Designs

- [architecture/display-crash-quarantine.md](./architecture/display-crash-quarantine.md)
  — scene quarantine for the crash-respawn loop. Designed and ProB-verified;
  implementation deferred by operator ruling (bead `lux-88ka`). Companion
  model: `display_crash_loop.tex` below.

## Element Migration (completed)

The migration of all 25 element kinds onto the Element-ABC / Hub-Display path
is **complete** (epic `lux-xs7r`, closed 2026-07-27; the legacy path is
deleted). These documents are the historical record:

- [architecture/migration/README.md](./architecture/migration/README.md) —
  the plan and its per-element design documents (progress, slider, table,
  composites, and the rest).
- [architecture/element-migration-audit.md](./architecture/element-migration-audit.md)
  — the per-element map the migration worked from.
- [architecture/skill-tool-reusability-audit.md](./architecture/skill-tool-reusability-audit.md)
  — the audit behind DES-040's tools-vs-skills split.

## Current Architecture

- [architecture/system.tex](./architecture/system.tex) →
  [architecture/system.pdf](./architecture/system.pdf)

This is the current/intermediate system view, not the rewrite target.

## Formal Specs

Z specifications, each ProB-model-checked and committed as a regression
artifact — re-run `fuzz` and the model-check whenever the modeled code
changes. A coverage audit beside a spec maps its test partitions to the tests
that cover them.

Current and authoritative:

| Model | Coverage audit | What it proves |
|---|---|---|
| [display_lifecycle.tex](./display_lifecycle.tex) → [pdf](./display_lifecycle.pdf) | [display_lifecycle_coverage.md](./display_lifecycle_coverage.md) | Display-singleton spawn/reap/bind lifecycle (DES-037/038): singleton-serving, never-unlink-live, no-two-winners, deadlock-freedom |
| [hub_replicator.tex](./hub_replicator.tex) → [pdf](./hub_replicator.pdf) | [hub_replicator_coverage.md](./hub_replicator_coverage.md) | Hub→Display replication: coalescing, torn-read exclusion, send-failure recovery, menu re-mark (I6). The menu leg predates the menu epic's callback rework — reconciliation tracked as `lux-ptji` |
| [frame_expiry.tex](./frame_expiry.tex) | [frame_expiry_coverage.md](./frame_expiry_coverage.md) | Frame TTL expiry: a frame with a future deadline is always shown; every removal path disarms |
| [board_ordering.tex](./board_ordering.tex) | [board_ordering_coverage.md](./board_ordering_coverage.md) | The beads applet's board ordering: the slot never goes backwards, nor does the display, and the display never shows a board the slot refused. Three fidelity controls reproduce the defects the design closes — the code as it stood ([current](./board_ordering_current_buggy.tex)) and the two half-fixes ([counter](./board_ordering_gate_only_buggy.tex), [re-read](./board_ordering_reread_only_buggy.tex)) |
| [header_toggle_reconciliation.tex](./header_toggle_reconciliation.tex) | — | The collapsing header's open state across the click-to-re-push window: one click moves the rendered state once and fires once, the optimistic value never outlives its window, and the Hub wins once it has spoken. Three fidelity controls reproduce the shipped double-step ([unconditional write](./header_toggle_reconciliation_unconditional_buggy.tex)) and the two ways a careless fix goes wrong ([stale pending](./header_toggle_reconciliation_stale_pending_buggy.tex), [firing against the Hub value](./header_toggle_reconciliation_refire_buggy.tex)) |
| [patch_application.tex](./patch_application.tex) → [pdf](./patch_application.pdf) | — | Patch crash-freedom: no agent patch can terminate the display; rejected patches are atomic |
| [patch_atomicity.tex](./patch_atomicity.tex) → [pdf](./patch_atomicity.pdf) | — | Table-patch rollback atomicity (B6): a failed patch leaves no partial state |
| [tab_bar_selection.tex](./tab_bar_selection.tex) → [pdf](./tab_bar_selection.pdf) | — | Tab-bar selection state machine |
| [commit_on_idle_reconciliation.tex](./commit_on_idle_reconciliation.tex) → [pdf](./commit_on_idle_reconciliation.pdf) | — | Continuous-edit commit-on-idle reconciliation for non-atomic inputs |
| [reconciliation_hub_reject.tex](./reconciliation_hub_reject.tex) → [pdf](./reconciliation_hub_reject.pdf) | — | Hub rejection of a reconciliation commit: the display converges to the Hub's value |
| [display_crash_loop.tex](./display_crash_loop.tex) | — | Crash-respawn quarantine (deferred design, `lux-88ka`); the `_buggy` variants ([1](./display_crash_loop_buggy.tex), [2](./display_crash_loop_earlyexit_buggy.tex)) are fidelity controls that reproduce the defect the design closes |

Legacy (model the pre-Hub/Display single-process design):

- [architecture/display-server.tex](./architecture/display-server.tex) →
  [pdf](./architecture/display-server.pdf)
- [architecture/workspace-model.tex](./architecture/workspace-model.tex) →
  [pdf](./architecture/workspace-model.pdf)

The legacy specs' refinement tests still hold the current display code to their
models, but they predate the Hub/Display split and are not the main narrative
architecture set.

## ImGui Reference

- [imgui/primitive-catalog.md](./imgui/primitive-catalog.md)

A comprehensive Dear ImGui / ImPlot widget and primitive reference. This is a
timeless API reference, independent of Lux's architecture, and is kept current.

## Archive

- [archive/README.md](./archive/README.md)
- [archive/claude-code-lux.tex](./archive/claude-code-lux.tex) →
  [pdf](./archive/claude-code-lux.pdf)
- [archive/coverage-audit.md](./archive/coverage-audit.md)

Superseded documents retained for history. Each carries an archived banner.
They do not describe the current system; see [`archive/README.md`](./archive/README.md)
for why each was archived. Older migration notes and spike proof points not in
the archive can be recovered from git history.

## Alternative Concepts

- [concepts/self-extending-display.md](./concepts/self-extending-display.md)
- [concepts/extension-architecture.tex](./concepts/extension-architecture.tex) →
  [pdf](./concepts/extension-architecture.pdf)
- [concepts/pharo-inspiration.md](./concepts/pharo-inspiration.md)

These are not approved plans, are not the canonical Lux architecture, and are
not under active development.

## Product Thesis

- [prfaq.tex](../prfaq.tex) → [prfaq.pdf](../prfaq.pdf)

The Working-Backwards PR/FAQ (at the repo root, not under `concepts/`). Unlike
the alternative concepts above, this is a living product-thesis document under
the org's release workflow — it is updated when a change shifts product
direction or validates a risk assumption, not an abandoned concept.
