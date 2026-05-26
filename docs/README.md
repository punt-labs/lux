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

## Historical Material

Older migration notes, archived io-model drafts, and spike proof points were
removed from the live docs tree to reduce confusion. If you need that material,
recover it from git history instead of treating it as current guidance.

## Alternative Concepts

- [concepts/self-extending-display.md](./concepts/self-extending-display.md)
- [concepts/extension-architecture.tex](./concepts/extension-architecture.tex)
- [concepts/prfaq.tex](./concepts/prfaq.tex)
- [concepts/pharo-inspiration.md](./concepts/pharo-inspiration.md)

These are not approved plans, are not the canonical Lux architecture, and are
not under active development.
