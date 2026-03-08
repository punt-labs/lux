# Contributing to Lux

Thank you for your interest in contributing to lux. This guide covers what you need to get started.

## Getting Started

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) for dependency management

### Setup

```bash
git clone https://github.com/punt-labs/lux.git
cd lux
uv sync --extra dev
```

### Verify your setup

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/ tests/
uv run pyright
uv run pytest
```

All five must pass with zero errors before any commit.

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

Every commit must pass:

```bash
uv run ruff check .           # Linting
uv run ruff format --check .  # Formatting
uv run mypy src/ tests/       # Type checking (mypy)
uv run pyright                 # Type checking (pyright)
uv run pytest                  # Tests
```

### Running Tests

```bash
uv run pytest                              # Unit tests (fast)
uv run pytest -m integration               # Integration tests (requires display)
uv run pytest -m e2e                       # End-to-end tests (full stack)
```

New features should have unit tests at minimum.

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
