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

## Current Architecture

- [architecture/system.tex](./architecture/system.tex)
- [architecture/system.pdf](./architecture/system.pdf)

This is the current/intermediate system view, not the rewrite target.

## Formal Specs

- [architecture/display-server.tex](./architecture/display-server.tex)
- [architecture/workspace-model.tex](./architecture/workspace-model.tex)

These are formal or appendix-style documents modeling the legacy
single-process design. They are useful, and their refinement tests still hold
the current display code to their models, but they are not the main narrative
architecture set and they predate the Hub/Display split.

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

- [concepts/prfaq.tex](./concepts/prfaq.tex)

The Working-Backwards PR/FAQ. Unlike the alternative concepts above, this is a
living product-thesis document under the org's release workflow — it is updated
when a change shifts product direction or validates a risk assumption, not an
abandoned concept.
