# Docs Guide

Use this file when the repo's documentation feels contradictory.

Lux has documentation for:

- the current/intermediate implementation
- the target architecture
- coding standards
- formal models
- migration history
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
- [architecture/target/introspection-api.md](./architecture/target/introspection-api.md)

These documents describe the intended Hub-authoritative architecture.

## Current Architecture

- [architecture/system.tex](./architecture/system.tex)
- [architecture/system.pdf](./architecture/system.pdf)

This is the current/intermediate system view, not the rewrite target.

## Formal Specs

- [architecture/display-server.tex](./architecture/display-server.tex)
- [architecture/workspace-model.tex](./architecture/workspace-model.tex)
- [architecture/claude-code-lux.tex](./architecture/claude-code-lux.tex)

These are formal or appendix-style documents. They are useful, but they are
not the main narrative architecture set.

## Historical / Migration Material

- [architecture/luxd-impl.md](./architecture/luxd-impl.md)
- [architecture/archive/](./architecture/archive)
- [oo-refactor/README.md](./oo-refactor/README.md)

These are unmaintained historical materials kept only while useful content is
being harvested into the canonical docs. Do not start here for architecture
intent, do not cite them as authority, and do not extend them.

## Proof Points, Not Product Docs

- [../spikes/io_model_v1/README.md](../spikes/io_model_v1/README.md)

Use these to understand what was prototyped or validated. Do not treat them as
the product's canonical architecture.

## Alternative Concepts

- [concepts/self-extending-display.md](./concepts/self-extending-display.md)
- [concepts/extension-architecture.tex](./concepts/extension-architecture.tex)
- [concepts/prfaq.tex](./concepts/prfaq.tex)
- [concepts/pharo-inspiration.md](./concepts/pharo-inspiration.md)

These are not approved plans, are not the canonical Lux architecture, and are
not under active development.
