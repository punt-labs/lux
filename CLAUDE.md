# Agent Instructions

This project follows [Punt Labs standards](https://github.com/punt-labs/punt-kit).

## No "Pre-existing" Excuse

There is no such thing as a "pre-existing" issue. If you see a problem — in code you wrote, code a reviewer flagged, or code you happen to be reading — you fix it. Do not classify issues as "pre-existing" to justify ignoring them. Do not suggest that something is "outside the scope of this change." If it is broken and you can see it, it is your problem now.

## What Is Lux?

Lux is a **visual output surface for Claude Code**. Vox gives agents a voice; Lux gives agents a screen — tables, charts, dashboards, and interactive elements rendered in a native ImGui window via Unix socket IPC.

- **PyPI package**: `punt-lux`
- **CLI command**: `lux`
- **Projection surfaces**: library, CLI, MCP server, plugin
- **Stage**: v0.16.1 (v2 vision in `docs/v2-vision.md`)

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

## Product Vision

The PR/FAQ (`lux-prfaq-v2.tex`) is the authoritative source for product vision, target market, competitive positioning, phasing, risk assessment, and "what we are not building." When there are questions about scope, priorities, or product direction, consult the PR/FAQ first. The vision document (`docs/v2-vision.md`) is the north-star intent.

**v2 thesis:** Lux is a self-extending, GPU-accelerated display server for terminal-hosted AI agents. Closed core, open extension surface. Everything user-visible is an extension. Extensions are LLM-authored on demand and shared via a community registry. The protocol is the API surface — if an agent can describe it as JSON, Lux renders it.

**Pharo relationship:** Complementary, not competing. Pharo (via Postern) is the ambitious live-environment substrate. Lux is the pragmatic local-first path grounded in Python's ecosystem. See `docs/v2-vision.md` § "The Pharo Relationship."

## Design Decision Log

`DESIGN.md` is the authoritative record of design decisions, prior approaches, and their outcomes. Every design change must be logged there before implementation. Consult it before proposing any change — do not revisit a settled decision without new evidence.

The architecture specification (`docs/architecture.tex` for v1, `docs/v2-architecture.tex` for v2) documents the system architecture. Both compile to PDF.

## Scratch Files

Use `.tmp/` at the project root for scratch and temporary files — never `/tmp`. The `TMPDIR` environment variable is set via `.envrc` so that `tempfile` and subprocesses automatically use it. Contents are gitignored; only `.gitkeep` is tracked.

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

## Workflow: Ethos Missions and Pipelines

Use ethos missions for structured delegation. Every non-trivial change goes through a typed mission contract with file-level write-set boundaries, bounded rounds, and an append-only audit trail.

**Mission archetypes** — declare `type:` on the contract:

| Archetype | Purpose | Budget | Write-set constraints |
|-----------|---------|--------|-----------------------|
| `implement` | Code change with specific outcome | 3 rounds | Any path |
| `design` | Produce a design document | 2 rounds | `*.md`, `docs/**` |
| `test` | Add or improve tests | 2 rounds | `*_test.*`, `tests/**`, `docs/**` |
| `review` | Read and report findings | 1 round | `*.md`, `*.yaml`, `.tmp/**` |
| `report` | Gather info and summarize (read-only) | 1 round | Empty allowed |
| `task` | Execute a specific instruction | 3 rounds | Any path |

**Pipeline selection** — match the pipeline to the nature of the work, not just its size:

| Pipeline | Stages | Use when |
|----------|--------|----------|
| `quick` | implement → review | Small, well-understood change |
| `standard` | design → implement → test → review → document | Default feature work |
| `full` | prfaq → spec → design → implement → test → coverage → review → document → retro | Large or cross-cutting work |
| `product` | prfaq → design → implement → test → review → document | New user-facing feature |
| `formal` | spec → design → implement → test → coverage → review → document | Protocol or state machine |
| `docs` | design → review | Documentation-only change |
| `coe` | investigate → root-cause → fix → test → document | Bug that keeps coming back |
| `coverage` | measure → test → verify | Targeted test improvement |

**Instantiate a pipeline:**

```bash
ethos mission pipeline instantiate standard \
  --leader claude --worker rmh --evaluator djb \
  --var feature=hook-stdin-fix --var target=hooks/signal-beads.sh
```

This creates one mission per stage, wired with `depends_on` edges. The worker picks up stage 1, submits a result, the leader reflects and advances.

**Contract field notes:**

- Use `inputs.ticket` (not `inputs.bead` — deprecated alias).
- `ethos mission lint` suggests a pipeline and flags common contract issues.
- Escalation only goes up. If `quick` reveals unexpected scope, escalate to `standard`. Never demote mid-flight.

**Specialist agents** — delegate to ethos agents, not bare agents:

| Agent | Domain | Use for |
|-------|--------|---------|
| `rmh` | Python implementation | All Python code changes in Lux |
| `adb` | Infrastructure, CI/CD | CI workflows, build scripts, cross-repo tooling |
| `djb` | Security review | Extension safety, consent model, trust boundaries |
| `mdm` | CLI design | CLI commands, UX, flags, help text |
| `kpz` | ML inference | LLM integration, agent SDK |

## Knowledge Propagation Protocol

After merging a PR that introduces new patterns, design decisions, or hard-won debugging insights, propagate knowledge outward before closing the session:

### 1. Document in DESIGN.md

Log the decision in DESIGN.md. Include: what changed, why, what was rejected, and what evidence drove the decision.

### 2. Propagate to punt-kit

If the pattern is reusable across projects:

- **Pattern file** — Create or update `punt-kit/patterns/<name>.md` if a new architectural pattern emerged.
- **Standard update** — Update `punt-kit/standards/*.md` if an existing standard was invalidated or needs refinement.
- **PR directly** for factual corrections. **Bead** in punt-kit for broader work.

### 3. Hand off to public-website

If the discovery is interesting to external developers:

- Create a **bead** in `public-website/` describing what to add (blog post, docs page).
- Include: the story arc, technical details, and audience.

### 4. Update prfaq.tex and README

If the feature was on the roadmap, move it to "Shipped" in both `README.md` and `lux-prfaq-v2.tex`. Recompile the PDF. Features should never remain listed as "Next" after they ship.

### Checklist

```text
[ ] DESIGN.md updated (if design decision)
[ ] punt-kit patterns/ or standards/ updated (if reusable pattern)
[ ] public-website bead created (if externally interesting)
[ ] README.md and lux-prfaq-v2.tex updated (if shipped feature)
[ ] lux-prfaq-v2.pdf recompiled
```

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
