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

## Characterization tests

The `tests/characterization/` package is the migration safety net introduced
in PR #lux-edvm. Every MCP tool registered in `src/punt_lux/tools/tools.py`
has at least one captured input/response snapshot in
`tests/characterization/snapshots/`. The migration PRs (`lux-b14i` through
`lux-uxvj`) verify byte-identical output by replaying the corpus.

**Run the gate**:

```bash
make snapshot-parity          # replay every snapshot, fail on any drift
make snapshot-record          # rebuild the corpus from build_corpus.py
```

`make snapshot-parity` is also wired into `.github/workflows/test.yml`, so
every PR is gated automatically.

**How the corpus is built**:

- `snapshot.py` — frozen dataclass `Snapshot(tool, inputs, setup, response)`
  with `from_file` / `to_file` / `matches` / `diff` / `describe_mismatch`.
  Comparison is strict string equality; single-line responses diff cleanly.
  `REPO_ROOT_TOKEN` (the literal `<REPO_ROOT>`) stands in for the project
  root in inputs so the corpus is portable across checkouts.
- `exerciser.py` — `ToolExerciser.call(tool, inputs, setup)` invokes a tool
  under a stub configuration that patches `DisplayPaths.is_running` and
  both `_get_client` lookups (`tools.tools._get_client` *and*
  `tools.connection._get_client` — the `@_query_tool` family closes over
  the latter). Returns the tool's response or raises `ToolCallError`; no
  `T | None` on the value path (PY-EH-8).
- `build_corpus.py` — every scenario lives in `SCENARIOS`. The build
  canonicalises each setup through JSON-sort-keys before recording so the
  on-disk file and the in-memory replay agree on dict iteration order.
- `test_parity.py` — parametrizes over every JSON file in `snapshots/`,
  asserts `Snapshot.matches(observed)` after running the exerciser. One
  guard test refuses an empty corpus so "I forgot to regenerate" fails
  loud rather than silently passing zero parametrized cases.

**When a tool's behavior intentionally changes**:

1. Edit `build_corpus.py` if the scenario shape needs updating (new inputs,
   different stub setup).
2. Run `make snapshot-record` to regenerate every JSON file.
3. Inspect the diff — every snapshot whose response actually changed should
   be visible in `git diff tests/characterization/snapshots/`. Snapshots
   whose response did NOT change are still rewritten with the same content;
   the diff for those should be empty.
4. Commit the regenerated corpus in the same PR as the production change.

**Manual regression check** (sanity gate the corpus exists at all): change
one byte of a tool's output — for example, edit `"ack:"` to `"ACK:"` in
`show()` — and run `make snapshot-parity`. Six snapshots fail with a
unified diff each. Revert the production change; the gate returns to
green. `test_parity.py`'s module docstring shows the exact diff format
the migration PRs are reviewed against.

**Adding a new tool to the corpus**: append a `Scenario(name=..., tool=...,
inputs=..., setup=...)` to the relevant category in `build_corpus.py`,
then `make snapshot-record` and `make snapshot-parity`. Coverage is
audited by checking that every name in `punt_lux.tools.__all__` (minus
`mcp` and `run_mcp_session`) has at least one snapshot whose `tool` field
matches.

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
