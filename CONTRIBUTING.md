# Contributing to Lux

Thank you for your interest in contributing to Lux. This guide covers what you need to get started.

## Getting Started

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) for dependency management
- Node.js with `npx` for Markdown linting and pyright
- Git and Make

### Setup

Clone the repository:

```bash
git clone https://github.com/punt-labs/lux.git
```

Enter it:

```bash
cd lux
```

Install dependencies, including the window renderer (the dev group installs by
default):

```bash
uv sync --extra display
```

### Verify your setup

Run the full quality gate:

```bash
make check
```

It must pass before any commit. See [Quality Gates](#quality-gates).

## Development Workflow

### Branch Discipline

All changes go on feature branches. Never commit directly to `main`.

```bash
git checkout -b feat/short-description main
```

| Prefix | Use |
|--------|-----|
| `feat/` | New features |
| `fix/` | Bug fixes |
| `refactor/` | Code improvements |
| `docs/` | Documentation only |

### Commit Messages

Format: `type(scope): description`

```text
feat(display): add color picker element
fix(protocol): handle missing tooltip field
refactor(server): extract element validation
test(client): add reconnection tests
docs: update element reference
chore: bump imgui-bundle dependency
```

One logical change per commit. Small commits are preferred over large ones.

### Quality Gates

Every commit must pass the single gate:

```bash
make check
```

`make check` is authoritative; the `Makefile` is the source of truth for the
exact chain. `uv sync` installs the pinned dev-only PyPI package
`punt-oo-ratchet==0.2.0`, which supplies all three ratchets through the
`oo-ratchet` CLI (no embedded tooling). It runs the OO ratchet (`make check-oo`),
the coupling ratchet
(`make check-coupling`), the suppression ratchet (`make check-suppressions`),
`make lint`, `make type`, and `make test`. The OO ratchet compares OO scores
against `.oo-baseline.json` and fails if any metric regresses on a touched
file. After improving OO quality, run `make update-oo` and stage
`.oo-baseline.json` and `.oo-audit.jsonl` in the same commit.

Coupling uses Lux's broad stateless-value LCOM exemption and four wiring-hub
fan-out caps of 20, configured under `[tool.oo-ratchet.coupling]` in
`pyproject.toml`. Run `make update-coupling` after improvements. For an audited,
bounded bless, use `make bless-coupling FILES=a.py,b.py REASON="explanation"`;
this refuses metrics that exceed both their configured cap and baseline.
Stage `.oo-coupling-baseline.json` and `.oo-coupling-audit.jsonl` together.

`make lint` runs these:

```bash
uv run --extra display ruff check .
```

```bash
uv run --extra display ruff format --check .
```

```bash
npx markdownlint-cli2 "**/*.md" "#node_modules"
```

```bash
bash scripts/check-plugin-surface.sh
```

`make type` runs these. pyright runs through `npx` because the display extras
confuse uv's pyright wrapper:

```bash
uv run --extra display mypy src/ tests/
```

```bash
npx pyright src/ tests/
```

### Running Tests

Unit tests (the tier `make check` runs):

```bash
make test
```

Integration tests (no display needed):

```bash
make test-integration
```

End-to-end tests that need no GUI window:

```bash
make test-e2e
```

End-to-end tests that open a real ImGui window (local only):

```bash
make test-e2e-gui
```

New features should have unit tests at minimum.

### Running Your Changes

Reinstall the package and restart `luxd` and the Lux window through their
services, so they pick up your code changes:

```bash
make restart
```

The Claude Code plugin (its `plugin.json`, the `/lux` command, the session
hooks, and the skills) lives in `plugin/`, separate from the Python package in
`src/`. A marketplace install fetches only that directory. Load it for local
testing:

```bash
claude --plugin-dir plugin
```

Installing the CLI (`uv tool install`, `install.sh`, or `pip`) is unaffected:
the wheel ships `src/punt_lux` and never contained the plugin surface.

### Visual Verification

Capture the running Lux window to `.tmp/lux-screenshot.png`:

```bash
make screenshot
```

Write the capture somewhere else:

```bash
SCREENSHOT_OUT=/tmp/out.png make screenshot
```

This is for visual checks at the demo gate (`docs/WORKFLOW.md`). On Linux it
was verified on Ubuntu with a Wayland session running XWayland
(`DISPLAY` pointing at the X11 socket). It needs `import` and `convert`
(ImageMagick), `xwininfo` and `xprop` (x11-utils), `xdotool`, and
`systemd-inhibit` (systemd) on `PATH`. `scripts/screenshot.sh` finds the real
`luxd-display` window by matching `_NET_WM_PID`, not by title, and rejects a
capture that is almost a single color, such as the black image a locked
session produces. It is not part of `make check`; CI has no display to
capture.

On macOS, `make screenshot` runs `scripts/screenshot_macos.py` instead. It
needs `ffmpeg` (`brew install ffmpeg`) and the `display` extra. Grant your
terminal app **Screen Recording** permission (System Settings > Privacy &
Security > Screen Recording); a terminal that is still running may need a
restart before it applies. Raising the window uses System Events, which asks
once for Automation permission.

The macOS script keeps the same contract as the Linux one:

- It finds the window by the `luxd-display` PID, never by title.
- It removes the output file first and only writes a verified capture.
- It rejects a blank capture.

It captures what is on screen: `ffmpeg -f avfoundation` grabs the display the
window is on, then crops the window out. So it raises the window first, and
fails if another window still covers it, or if the window spans two displays.

For a series of captures at a fixed interval:

```bash
make screenshots SCREENSHOT_INTERVAL=5 SCREENSHOT_COUNT=12
```

By default this writes `.tmp/lux-screenshot-0001.png`,
`.tmp/lux-screenshot-0002.png`, and so on.

## Code Standards

- **Full type annotations** on every function signature. Avoid `Any` unless required by third-party APIs (e.g., ImGui bindings).
- **Double quotes.** Line length 88.
- **Immutable data models.** `@dataclass(frozen=True)` or pydantic with immutability.
- **No duplication.** If you see two copies, extract one abstraction.
- **No backwards-compatibility shims.** When code changes, callers change.

## Submitting Changes

1. Push your branch and open a pull request.
2. Ensure CI passes on all commits.
3. Respond to review feedback. Each fix commit must also pass quality gates.
4. Once approved and green, the PR will be merged.

### What Makes a Good PR

- Clear title and description explaining *why*, not just *what*.
- Small, focused scope. One concern per PR.
- Tests included for new behavior.
- README updated if user-facing behavior changed.
- CHANGELOG entry for notable changes.

## Reporting Bugs

Open an issue at [github.com/punt-labs/lux/issues](https://github.com/punt-labs/lux/issues) with:

- What you expected to happen.
- What actually happened.
- Steps to reproduce.
- Your environment (OS, Python version, lux version).

## Suggesting Features

Open an issue describing the problem you want to solve, not just the solution you have in mind. Context about your use case helps us evaluate the right approach.

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
