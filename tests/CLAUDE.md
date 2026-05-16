# Tests

## Pyramid

| Tier | Marker | Runs in CI | Command | What it covers |
|------|--------|------------|---------|----------------|
| 1 — Unit | *(none)* | yes | `make test` | Protocol serialization, scene management, element builders, widget state, display client |
| 2 — Integration | `@pytest.mark.integration` | yes | `uv run --extra display pytest -m integration` | Socket IPC, cross-component state, multi-element scenes |
| 3 — E2E | `@pytest.mark.e2e` | no | `uv run --extra display pytest -m e2e` | CLI args, process lifecycle, wire protocol end-to-end |
| 4 — Visual | manual | no | run lux, look at it | ImGui rendering correctness — cannot be automated without a display |

`make test` runs tiers 1 and 2. Tiers 3 and 4 are opt-in.

## Running tests

```bash
make test                                           # tiers 1-2, standard gate
make coverage                                       # tiers 1-2 with HTML report in htmlcov/
uv run --extra display pytest tests/test_foo.py -v  # single file, targeted
uv run --extra display pytest -m integration        # integration tier only
```

All targets use `--extra display` because the test suite imports display
modules for state-machine testing even when no GPU is present.

## Writing tests

**Protocol tests are the primary safety net.** Every element kind must
have a test that verifies the serialization roundtrip: build → serialize →
deserialize → compare. Protocol changes without roundtrip tests are
unshippable.

**Scene tests verify composition.** Multi-element scenes, tab switching,
window management, and detail panels must be tested at the scene level
even though visual correctness is manual.

**Test the failure path.** Every public function should have at least one
test for invalid input, one for a missing/unavailable dependency, and one
for a boundary condition. Happy-path-only tests are incomplete.

**Coverage increases with every change.** When you touch a file, its test
coverage must not decrease. New functions get tests; bug fixes get
regression tests.

## Conventions

**Markers** — use the standard tier markers:

```python
@pytest.mark.integration
@pytest.mark.e2e
@pytest.mark.slow   # benchmarks with latency assertions
```

**Unix socket paths** — macOS limits socket paths to ~104 characters.
Use `tempfile.mkdtemp(prefix="lux-")` for temporary socket paths, not
pytest's `tmp_path` (which produces long paths that exceed the limit).

**No skipping without a reason.** `@pytest.mark.skip` and
`@pytest.mark.xfail` must include a `reason=` and a bead ID for the fix.
Permanent skips are bugs.

**Mirror source structure.** `src/punt_lux/scene/manager.py` →
`tests/test_scene_manager.py`. Every source module has a counterpart.

## Visual testing

`display.py` and the rendering layer have no automated tests — correctness
is verified manually by running lux and looking at the output. This is the
largest testing gap in the codebase. Decomposing `display/server.py` into
smaller units is prerequisite to meaningful render tests; each extraction
improves testability. Until then: when changing rendering code, run
`make install` and exercise the affected element visually before
committing.
