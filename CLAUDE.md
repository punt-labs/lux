# Agent Instructions

This project follows [Punt Labs standards](https://github.com/punt-labs/punt-kit).

## What Is Lux?

Lux is the **visual counterpart to Vox** (punt-vox). Vox gives agents a voice; Lux gives agents visual output — image and diagram generation with multi-provider support. It generalizes `langlearn-imagegen` into a standalone building block that any project can compose.

- **PyPI package**: `punt-lux`
- **CLI command**: `lux`
- **Projection surfaces**: library, CLI, MCP server, REST API (universal access pattern)
- **Stage**: alpha (v0.0.0)

### Capabilities

- Multi-backend image generation (swap providers without changing calling code)
- Diagrams, illustrations, and visual assets from text descriptions
- Batch generation for learning materials and documentation

### Key Relationships

- **Vox** (`../tts/`) — audio counterpart; Lux follows the same architectural patterns
- **langlearn-imagegen** (`../langlearn-imagegen/`) — predecessor; Lux generalizes this into a standalone block
- **LangLearn** (`../langlearn/`) — orchestrator that will compose Lux for visual assets
- **Persona** (planned) — will provide character/style hints that Lux can consume

### Punt Labs Context

Punt Labs builds CLI tools, Claude Code plugins, and MCP servers that bring rigour to agentic software engineering. Core thesis: AI removes the time penalty from rigour. Every tool follows the same universal access pattern (library → CLI → MCP → REST) from a single codebase. The terminal is the primary interface.

## Vision / Inspiration

**Smalltalk as north star.** Pharo/Squeak's live, image-based environment is the long-term inspiration for what Lux could become. In Smalltalk, the Morphic UI treats every visible element as a live, inspectable, composable object — windows inside windows, drag anything, modify anything at runtime. Lux's composable element tree (windows, tabs, groups, collapsing headers nesting arbitrary children) is building toward the same idea, but with an LLM as the "programmer at the keyboard" instead of a human typing into a Smalltalk workspace.

**The endgame:** a Pharo-like live environment where the MCP server is the message bus, Lux is the Morphic layer, and the agent can introspect and reshape the UI while it's running. System browser, inspector, workspace — all draggable windows populated and driven by the agent. This would be a separate application built on top of Lux primitives, not part of Lux itself.

**What this means for primitives:** every element kind we add should be evaluated against "does this compose into a live environment?" Keep elements small, nestable, and data-driven. The protocol is the API surface — if an agent can describe it as JSON, Lux should render it.

## Quality Gates

Run before every commit. Zero violations, zero errors, all tests green.

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src/ tests/ && uv run pyright && uv run pytest
```

## Standards References

- [GitHub](https://github.com/punt-labs/punt-kit/blob/main/standards/github.md)
- [Workflow](https://github.com/punt-labs/punt-kit/blob/main/standards/workflow.md)
- [Python](https://github.com/punt-labs/punt-kit/blob/main/standards/python.md)
- [CLI](https://github.com/punt-labs/punt-kit/blob/main/standards/cli.md)
- [Distribution](https://github.com/punt-labs/punt-kit/blob/main/standards/distribution.md)

## Available Tooling

| Tool | What It Does |
|------|-------------|
| `punt init` | Scaffold missing files (CI, config, permissions, beads) |
| `punt audit` | Check compliance against Punt Labs standards |
| `punt audit --fix` | Auto-create missing mechanical files |
| `/punt reconcile` | LLM-powered contextual reconciliation (workflows, CLAUDE.md, permissions) |
