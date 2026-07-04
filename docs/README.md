# Docs Guide

Use this file when the repo's documentation feels contradictory.

Lux has documentation for:

- the current/intermediate implementation
- the target architecture
- coding standards
- formal models
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

## Coding Standard

- [standards/python-oo.md](./standards/python-oo.md)

This is the repo-level implementation standard. It is where Lux's OO-only
policy and ratchet enforcement live. It is not an architecture document.

## Target Architecture

- [architecture/target/README.md](./architecture/target/README.md)
- [architecture/target/topology.md](./architecture/target/topology.md)
- [architecture/target/ui-model.md](./architecture/target/ui-model.md)
- [architecture/target/element-contract.md](./architecture/target/element-contract.md)
- [architecture/target/introspection-api.md](./architecture/target/introspection-api.md)

These documents describe the intended Hub-authoritative architecture.

## Element Migration (active plan)

- [architecture/migration/README.md](./architecture/migration/README.md)
- [architecture/element-migration-audit.md](./architecture/element-migration-audit.md)
- [architecture/migration/progress-element-design.md](./architecture/migration/progress-element-design.md)

The ratified plan to move the 25 element kinds onto the Element-ABC / Hub-Display
path: five design decisions, 7-batch sequencing, and the per-element
verify-as-you-go process. Tracked as beads epic `lux-xs7r`.

## Current Architecture

- [architecture/system.tex](./architecture/system.tex)
- [architecture/system.pdf](./architecture/system.pdf)

This is the current/intermediate system view, not the rewrite target.

## Formal Specs

Current and authoritative:

- [display_lifecycle.tex](./display_lifecycle.tex) → [display_lifecycle.pdf](./display_lifecycle.pdf) — the ProB-verified display-singleton lifecycle (DES-037/038); partition [coverage](./display_lifecycle_coverage.md). Rebuild the PDF when the model changes.

Legacy (model the pre-Hub/Display single-process design):

- [architecture/display-server.tex](./architecture/display-server.tex)
- [architecture/workspace-model.tex](./architecture/workspace-model.tex)

The legacy specs' refinement tests still hold the current display code to their
models, but they predate the Hub/Display split and are not the main narrative
architecture set.

## ImGui Reference

- [imgui/primitive-catalog.md](./imgui/primitive-catalog.md)

A comprehensive Dear ImGui / ImPlot widget and primitive reference. This is a
timeless API reference, independent of Lux's architecture, and is kept current.

## Archive

- [archive/README.md](./archive/README.md)
- [archive/claude-code-lux.tex](./archive/claude-code-lux.tex)
- [archive/coverage-audit.md](./archive/coverage-audit.md)

Superseded documents retained for history. Each carries an archived banner.
They do not describe the current system; see [`archive/README.md`](./archive/README.md)
for why each was archived. Older migration notes and spike proof points not in
the archive can be recovered from git history.

## Alternative Concepts

- [concepts/self-extending-display.md](./concepts/self-extending-display.md)
- [concepts/extension-architecture.tex](./concepts/extension-architecture.tex)
- [concepts/pharo-inspiration.md](./concepts/pharo-inspiration.md)

These are not approved plans, are not the canonical Lux architecture, and are
not under active development.

## Product Thesis

- [prfaq.tex](../prfaq.tex) → [prfaq.pdf](../prfaq.pdf)

The Working-Backwards PR/FAQ (at the repo root, not under `concepts/`). Unlike the alternative concepts above, this is a
living product-thesis document under the org's release workflow — it is updated
when a change shifts product direction or validates a risk assumption, not an
abandoned concept.
