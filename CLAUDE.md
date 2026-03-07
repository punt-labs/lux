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
