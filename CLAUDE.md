# Agent Instructions

This project follows [Punt Labs standards](https://github.com/punt-labs/punt-kit).

## What Is Lux?

Lux is a **visual output surface for Claude Code**. Vox gives agents a voice; Lux gives agents a screen — tables, charts, dashboards, and interactive elements rendered in a native ImGui window via Unix socket IPC.

- **PyPI package**: `punt-lux`
- **CLI command**: `lux`
- **Projection surfaces**: library, CLI, MCP server, plugin
- **Stage**: v0.5.0

### Capabilities

- Composable element tree: text, tables, plots, buttons, inputs, sliders, checkboxes, combos, color pickers
- Layout containers: groups (columns), tabs, collapsing headers, floating windows
- Built-in table filtering (search + combo) at 60fps with zero MCP round-trips
- Scene-based updates via JSON patch protocol over Unix sockets
- Auto-spawn: display server starts on first `show()` call

### Key Relationships

- **Vox** (`../vox/`) — audio counterpart; Lux follows the same plugin/release patterns
- **LangLearn** (`../langlearn/`) — orchestrator that will compose Lux for visual assets
- **claude-plugins** (`../claude-plugins/`) — marketplace catalog entry

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

## Documentation Discipline

**CHANGELOG.** Entries are written in the PR branch, before merge -- not retroactively on main. If a PR changes user-facing behavior and the diff does not include a CHANGELOG entry, the PR is not ready to merge. Follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format. Add entries under `## [Unreleased]`. Categories: Added, Changed, Deprecated, Removed, Fixed, Security.

**README.** Update README.md when user-facing behavior changes (new elements, commands, defaults, config). The README is the first thing users see -- it must stay accurate on every merge to main.

**PR/FAQ.** Update prfaq.tex when the change shifts product direction or validates/invalidates a risk assumption. The PR/FAQ is a living document, not a launch artifact.

## Pre-PR Checklist

- [ ] **CHANGELOG entry** included in the PR diff under `## [Unreleased]` (see Documentation Discipline above)
- [ ] **README updated** if user-facing behavior changed
- [ ] **prfaq.tex updated** if the change shifts product direction or validates/invalidates a risk
- [ ] **Quality gates pass** — `uv run ruff check . && uv run ruff format --check . && uv run mypy src/ tests/ && uv run pyright && uv run pytest`

### Code Review Flow

Do **not** merge immediately after creating a PR. Expect **2–6 review cycles** before merging.

1. **Create PR** — push branch, open PR via `mcp__github__create_pull_request`. Prefer MCP GitHub tools over `gh` CLI.
2. **Request Copilot review** — use `mcp__github__request_copilot_review`.
3. **Watch for feedback in the background** — `gh pr checks <number> --watch` in a background task or separate session. Do not stop waiting. Copilot and Bugbot may take 1–3 minutes after CI completes.
4. **Read all feedback** via MCP: `mcp__github__pull_request_read` with `get_reviews` and `get_review_comments`.
5. **Take every comment seriously.** Do not dismiss feedback as "unrelated to the change" or "pre-existing." If you disagree, explain why in a reply.
6. **Fix and re-push** — commit fixes, push, re-run quality gates.
7. **Repeat steps 3–6** until the latest review is **uneventful** — zero new comments, all checks green.
8. **Merge only when the last review was clean** — use `mcp__github__merge_pull_request` (not `gh pr merge`).

## Release Process

Lux is a **CLI + Plugin Hybrid** project. Releases publish to both PyPI and the marketplace.

### Release command

```bash
punt release <version>
```

### Propagation checklist (post-release)

After `punt release` completes, three manual propagation steps are required:

1. **Marketplace catalog** — update `claude-plugins/.claude-plugin/marketplace.json` with the new `ref` tag and `version`, commit, push
2. **install-all.sh** — update `punt-kit/install-all.sh` with the new install.sh SHA (`git log -1 --format='%H' -- install.sh`), commit, push to main
3. **install.sh SHA in README** — if the README references a pinned install.sh URL, update the SHA there too

### Release scripts

| Script | Purpose |
|--------|---------|
| `scripts/release-plugin.sh` | Swaps plugin.json name from `lux-dev` → `lux`, removes dev commands. Called by `punt release`. |
| `scripts/restore-dev-plugin.sh` | Restores dev plugin state on main after a release tag. Called by `punt release`. |

### Gotchas from v0.5.0 release

- `.gitignore` must cover all transient files (`.coverage`, `*.ini`, `demos/`, `__pycache__/`, LaTeX build artifacts) — `punt release` checks for a clean working tree
- The release-plugin.sh and restore-dev-plugin.sh scripts must exist before first release — `punt release` expects them for hybrid projects
- Marketplace propagation is not automatic — `punt release` does not create a PR in claude-plugins

## Available Tooling

| Tool | What It Does |
|------|-------------|
| `punt init` | Scaffold missing files (CI, config, permissions, beads) |
| `punt audit` | Check compliance against Punt Labs standards |
| `punt audit --fix` | Auto-create missing mechanical files |
| `/punt reconcile` | LLM-powered contextual reconciliation (workflows, CLAUDE.md, permissions) |
