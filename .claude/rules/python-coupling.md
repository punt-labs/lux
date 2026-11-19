---
paths:
  - "**/*.py"
---

# Module Coupling Standards

## PL-CU-1: Efferent Coupling (Fan-Out)

**Statement**: A module should not import from too many other internal
modules. High efferent coupling means the module knows too much about
the rest of the system — a change in any dependency can break it.

**Criterion**:

- Pass: module imports from <= 10 internal modules
- Pass (`__main__.py`): <= 15 (CLI entry points legitimately wire many modules)
- Pass (three wiring hubs configured in `pyproject.toml`): <= 20
- Fail: module imports from > 10 internal modules (> 15 for `__main__.py`)

**Tooling**:

- `oo-ratchet coupling` — `efferent_coupling` metric
- Fix: extract a facade or mediator that the module imports instead of
  importing each dependency directly

Lux uses `punt-oo-ratchet` 0.3.0 with `stateless-values = "any"` to retain
the broad stateless-value LCOM exemption. Exact-path hub caps live in
`[tool.oo-ratchet.coupling.caps]`. Run `make update-coupling` after improvements;
use repository-relative paths with
`make bless-coupling FILES=src/punt_lux/a.py,src/punt_lux/b.py REASON="explanation"`
for an audited bounded bless (`--rebaseline-files ... --reason ...`). Metrics above both
their cap and baseline are refused.

## PL-CU-2: Circular Imports

**Statement**: No module should participate in an import cycle. A imports
B which imports A means neither can be understood in isolation — they
are bidirectionally coupled. In Python, circular imports also cause
runtime `ImportError` when import order is wrong.

**Criterion**:

- Pass: module participates in zero import cycles
- Fail: module is part of any cycle in the internal import graph

**Tooling**:

- `oo-ratchet coupling` — `circular_imports` metric (1 if in cycle, 0 if not)
- Fix: break the cycle by extracting shared types into a separate module
  that both sides import, or use `TYPE_CHECKING` guards for annotation-only
  imports

## PL-CU-3: Interface Width (Public Names)

**Statement**: A module should expose a narrow public interface. Every
public name is a contract — consumers can depend on it, and changing it
is a breaking change. Fewer public names mean a more stable, easier to
maintain module.

**Criterion**:

- Pass: module exposes <= 15 public names (via `__all__` if present,
  otherwise counted as public classes, functions, and constants)
- Pass (`__main__.py`): <= 100 (CLI modules expose many commands by design)
- Fail: module exposes > 15 public names (> 100 for `__main__.py`)

**Tooling**:

- `oo-ratchet coupling` — `public_names` metric
- Fix: make internal helpers private (prefix with `_`), use `__all__` to
  control exports explicitly, extract internal utilities into separate modules

## PL-CU-4: God Module Detection

**Statement**: A module that is imported by more than half of all other
modules in the package is a god module — it is load-bearing and hard to
change without cascading breakage. Types modules and protocol definitions
legitimately have high fan-in; implementation modules should not.

**Criterion**:

- Flag for review: module is imported by > 50% of other modules AND is not
  a types/protocol module
- Not a hard fail — some modules are naturally central

**Tooling**:

- LLM review: check import graph for high fan-in implementation modules
- Future: afferent coupling metric in `oo-ratchet coupling`
