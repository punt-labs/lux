# Agent Instructions

This project follows [Punt Labs standards](https://github.com/punt-labs/punt-kit).

## No "Pre-existing" Excuse

There is no such thing as a "pre-existing" issue. If you see a problem — in code you wrote, code a reviewer flagged, or code you happen to be reading — you fix it. Do not classify issues as "pre-existing" to justify ignoring them. Do not suggest that something is "outside the scope of this change." If it is broken and you can see it, it is your problem now.

## What Is Lux?

Lux is a **visual output surface for Claude Code**. Vox gives agents a voice; Lux gives agents a screen. An ImGui window renders JSON element trees sent by agents over Unix socket IPC.

- **PyPI package**: `punt-lux`
- **CLI command**: `lux`
- **Version**: 0.16.1 (alpha)
- **Projection surfaces**: library, CLI, MCP server, plugin

### What Lux Is Good At

Tables and data display. The beads issue browser is the primary consumer — live DoltDB data in a filterable table with detail panel, rendered in a single `show_table()` call. Filters, search, and row selection run at 60fps with zero MCP round-trips. `show_dashboard()` composes metric cards, charts, and tables. `show_diagram()` renders auto-laid-out architecture diagrams.

The architecture is sound: MCP holds state, ImGui renders each frame from the latest JSON scene. This makes immediate mode "cached" — the agent sends state once, the display re-renders it every frame without further communication.

### Current State

24 element kinds covering ImGui's core primitives. Agents primarily use tables, text, plots, groups, and buttons today. The interactive widgets (sliders, color pickers, radio groups, input fields) are fully implemented and will see more usage as agents build richer UIs. The roadmap is full ImGui primitive coverage (15 additional widget kinds tracked in beads).

### Key Relationships

- **Vox** (`../vox/`) — audio counterpart; Lux follows the same plugin/release patterns
- **claude-plugins** (`../claude-plugins/`) — marketplace catalog entry

## Vision

**v1 (current):** A display canvas for Claude Code agents — tables, data, dashboards. The value is showing structured data that doesn't fit in a terminal. The protocol is the API surface — agents describe JSON, Lux renders it.

**v2 (future):** A Pharo-inspired live environment where the MCP server is the message bus and Lux is the Morphic rendering layer. The agent introspects and reshapes the UI at runtime. System browser, inspector, workspace — all driven by the agent. This is a separate application built on top of Lux primitives, not part of v1.

**Guiding constraint for v1:** do not add features in service of v2. Hone the data-display core. Every element kind should justify itself by current agent usage, not by v2 composability.

## Quality Gates

Run before every commit. Zero violations, zero errors, all tests green.

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src/ tests/ && uv run pyright && uv run pytest
```

## Ethos & Delegation

Identity: `agent: claude` per `.punt-labs/ethos.yaml`. Sub-agent calls (`Agent(subagent_type=…)`) match ethos identity handles.

Lux is Python (ImGui + Unix-socket IPC) with a strong UX and protocol-design dimension. Every element added to the protocol is a contract — agents render against it, and consumers compose it. Worker pairs split across the visual layer (UX / element design) and the implementation layer (Python / IPC / build). Within each row, the worker and evaluator must be distinct handles. Claude is the leader, never the evaluator.

| Task type | Worker | Evaluator |
|-----------|--------|-----------|
| New element kind / protocol extension | `edt` (Tufte) | `dna` (Norman) |
| Visual / layout / theming change | `dna` | `edt` |
| Python implementation (rendering, IPC, scenes) | `rmh` (Hettinger) | `gvr` (van Rossum) |
| Protocol amendment (JSON patch, Unix-socket schema) | `gvr` | `rmh` |
| CLI surface (`lux …` commands, plugin shell) | `mdm` (McIlroy) | `rop` (Pike) |
| MCP tool surface (`show`, `update`, `clear`, etc.) | `mdm` | `rmh` |
| GPU / inference / perf-sensitive rendering paths | `kpz` (Karpathy) | `rmh` |
| Security review (socket auth, IPC trust boundary) | `djb` (Bernstein) | `rmh` |
| Release / packaging / hybrid plugin pipeline | `adb` (Lovelace) | `mdm` |
| Frame-rate / latency budget verification | `kpz` | `edt` |

Use the `standard` pipeline for new elements and protocol changes (design → implement → review → ship). Use `quick` for bugfixes inside an existing element. Treat the JSON protocol as the API surface — any change there demands an evaluator distinct from the worker.

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
5. **Take every comment seriously.** There is no such thing as "pre-existing" or "unrelated to this change" — if you can see it, you own it. If you disagree, explain why in a reply.
6. **Fix and re-push** — commit fixes, push, re-run quality gates.
7. **Repeat steps 3–6** until the latest review is **uneventful** — zero new comments, all checks green.
8. **Merge only when the last review was clean** — use `mcp__github__merge_pull_request` (not `gh pr merge`).

## Release Process

Lux is a **CLI + Plugin Hybrid** project. Releases publish to both PyPI and the marketplace.

### Release command

Use `/punt:auto release` (the slash command), which runs the `punt release` CLI
through the playbook executor with LLM-driven error diagnosis. It handles all
11 phases automatically: preflight, version bump, build, release PR, tag, CI wait,
GitHub release, PyPI verify, post-release (README SHA bump), cross-repo propagation
(install-all.sh, marketplace, website), and verification. No manual steps
are needed after the command completes.

```text
/punt:auto release [version=X.Y.Z]
```

See [release-process.md](https://github.com/punt-labs/punt-kit/blob/main/standards/release-process.md) for
the full 11-phase specification.

### Release scripts

| Script | Purpose |
|--------|---------|
| `scripts/release-plugin.sh` | Swaps plugin.json name from `lux-dev` → `lux`, removes dev commands. Called by `punt release`. |
| `scripts/restore-dev-plugin.sh` | Restores dev plugin state on main after a release tag. Called by `punt release`. |

### Gotchas from v0.5.0 release

- `.gitignore` must cover all transient files (`.coverage`, `*.ini`, `demos/`, `__pycache__/`, LaTeX build artifacts) — `punt release` checks for a clean working tree
- The release-plugin.sh and restore-dev-plugin.sh scripts must exist before first release — `punt release` expects them for hybrid projects

## Available Tooling

| Tool | What It Does |
|------|-------------|
| `punt init` | Scaffold missing files (CI, config, permissions, beads) |
| `punt audit` | Check compliance against Punt Labs standards |
| `punt audit --fix` | Auto-create missing mechanical files |
| `/punt reconcile` | LLM-powered contextual reconciliation (workflows, CLAUDE.md, permissions) |
