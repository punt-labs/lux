# Tests

## Pyramid

| Tier | Marker | Runs in CI | Command | What it covers |
|------|--------|------------|---------|----------------|
| 1 — Unit | *(none)* | yes | `make test` | Protocol serialization, scene management, element builders, widget state, display client |
| 2 — Integration | `@pytest.mark.integration` | yes | `make test-integration` | Socket IPC, cross-component state, multi-element scenes |
| 3 — E2E | `@pytest.mark.e2e` | no | `make test-e2e` | CLI args, process lifecycle, wire protocol end-to-end |
| 4 — Visual | manual | no | run lux, look at it | ImGui rendering correctness — cannot be automated without a display |

`make test` runs tiers 1 and 2. Tiers 3 and 4 are opt-in.

## Running tests

```bash
make test                                           # tiers 1-2, standard gate
make test-integration                               # tier 2 only
make test-e2e                                       # tier 3 (requires display running)
make coverage                                       # tiers 1-2 with HTML report in htmlcov/
uv run --extra display pytest tests/test_foo.py -v  # single file, targeted
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

`display/server.py` and the rendering layer have no pixel-level automated
tests. Correctness is verified two ways:

**Introspection (partial, automatable).** The MCP tools `inspect_scene`,
`list_scenes`, and `screenshot` let agents query what the display server
has rendered — scene structure, element tree, and a PNG framebuffer
capture. E2E tests in `test_e2e.py` use introspection to verify that
scenes sent via the protocol appear correctly in the display's state.
This catches protocol-to-renderer wiring bugs without a human in the loop,
though it does not verify pixel-level rendering fidelity.

`screenshot` capture is currently in progress (DES-028) — the correct
capture timing in the ImGui render loop is unresolved. Once working, it
enables screenshot-based regression tests as part of the e2e tier.

**Manual verification (required for rendering fidelity).** When changing
rendering code, run `make install` and exercise the affected element
visually. The introspection API confirms the scene was received; a human
eye confirms it looks right. Until `display/server.py` is decomposed into
smaller testable units, there is no substitute for this step.
