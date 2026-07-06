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
unshippable. This is Level 1 of the [Round-trip test
procedure](#round-trip-test-procedure) below — the full migration gate runs
Levels 1–5 against the real boundary, never a stub.

**Scene tests verify composition.** Multi-element scenes, tab switching,
window management, and detail panels must be tested at the scene level
even though visual correctness is manual.

**Test the failure path.** Every public function should have at least one
test for invalid input, one for a missing/unavailable dependency, and one
for a boundary condition. Happy-path-only tests are incomplete.

**Coverage increases with every change.** When you touch a file, its test
coverage must not decrease. New functions get tests; bug fixes get
regression tests.

## Round-trip test procedure

Every element kind must survive the full round trip — agent → wire → Hub →
Display → (interaction) → Hub — verified at each level. This is the **migration
gate**: an element kind is not "migrated" until every level passes and Level 6 is
operator-confirmed. Levels 1–2 are pure serialization roundtrips (unit tests, no
process boundary); Levels 3–5 exercise the **real** Hub/Display boundary and must
never stub it. The levels build on each other; run every level each cycle. A green
Level 1 over a stubbed Level 4 is the exact failure mode that has bitten this
project before.

### Level 1 — Serialization roundtrip (unit, `make test`)

Build the element → `to_dict` → `from_dict` → assert equal. This exercises the
JSON codec surface. Every kind has one; a protocol change without it is
unshippable.

### Self-validation (every kind)

Every element kind must have tests for its `validate()` contract (DES-039).
At minimum:

- **valid input** → `validate()` returns `()` and the element renders;
- **malformed input** → the component-appropriate error is returned and the
  tree is NOT rendered — drive it through `show()` and assert the client is
  never called (`client.show.assert_not_called()`);
- **nested malformed input** → a bad element inside a composite is collected by
  the walk across the hierarchy — assert via `show()` with the element nested
  in every child-bearing container, not just `group`.

Boundary cases count: a table validates ragged rows, non-scalar cells, and
non-list `columns`/`rows` (a present-but-`null` field decodes to `None` and
must report, not crash); a tree validates non-mapping and label-less nodes. A
structural guard test must fail if a new container kind omits `child_elements()`
so nested elements can never silently skip the walk. An element kind is not
"self-validating" — the migration gate — until these pass.

### Level 2 — Wire roundtrip (unit/integration)

The Hub→Display wire is the `SceneMessage` codec (`protocol/messages/scene.py`):
it serializes to a dict, and each **ABC element** crosses as a base64-encoded
pickled `_pickled` entry inside that dict, while legacy elements cross as plain
dicts. Build a scene containing the element → serialize the scene message →
deserialize → assert the element compares equal. This is a **different surface**
from Level 1: an ABC kind's wire form is the pickled `_pickled` entry, its Level-1
form is the plain JSON dict, and both must pass. (The `checkbox` half-migration
slipped through because the pickle path was exercised while the JSON-encode
asymmetry went untested.)

### Level 3 — Hub/Display crossing (integration)

Install the element into `HubDisplay` (the authoritative Hub store, `domain/hub/`)
→ push to the Display → assert the Display holds an equal replica. Use the real
domain objects, not a stub. This proves UI state crosses the process boundary
intact.

### Level 4 — Interaction roundtrip / D21 (integration, interactive kinds only)

For kinds that fire events (button, checkbox, dialog, future inputs), drive the
**full leg** end to end: Display-side `fire(event)` → the wrapped handler emits a
`RemoteEventHandlerInvocation` over the **real socket** → the Hub resolves the
element and fires the real handler **once** on its authoritative copy → the Hub
re-pushes the updated scene. The test **must not** hand-construct the invocation
or `MagicMock` the client — that stubs the exact boundary the round trip exists to
prove. Assert: the handler ran exactly once, on the Hub's copy, and the re-push
reflects the mutation.

**The standing gate for this level is the business-event-loop harness**
(`tests/e2e/`, `@pytest.mark.integration`, design of record
`docs/architecture/e2e-harness-design.md`). It wires a windowless production
`DisplayServer` to the production Hub dispatch across the shipped
`InMemoryConnection` — the same `Connection` interface `LineSocket` implements —
and proves the full bidirectional loop for a **composed** surface: an injected
interaction crosses the faithful boundary, the real handler runs once on the
Hub's authoritative `HubDisplay` copy, a business event a real subscriber
receives is published, the simulated agent reacts by pushing a change back, and
the re-pushed Display replica reflects it (invariants I1–I6). An interactive
kind is **Level-4 green** when it has a passing `Scenario` in that harness;
adding a migrated kind is one more `Scenario` value, not new assertion code. The
harness injects by firing the replica's own wrapped handler — the exact call
`ButtonRenderer.render` makes on a real click — so the crossed invocation is
byte-identical to a real click's; only the GLFW pixel hit-test is deferred (with
the screenshot layer, DES-028).

### Level 5 — Introspection verification (integration)

`render_path` and `resolved_props` are the introspection primitive added by the
migration work (bead lux-b5wy). The current `inspect_scene` returns only
`{scene_id, elements}`, so this level becomes runnable once that primitive lands —
building it is part of the first migration PR. Once present, query `inspect_scene`
and assert, without looking at pixels: `render_path` is `"abc"` for the migrated
element (`"legacy"` for a not-yet-migrated one), and `resolved_props` reads back
the element's state including defaults. This is how each migration is verified
programmatically rather than by eyeballing the window.
Note: Hub-authoritative post-interaction state is a Batch-2 concern — the
display-side query reads the display snapshot, not luxd's `HubDisplay`, so do not
assert Hub authority from the display side.

### Level 6 — Manual visual confirmation (tier 4, required for rendering)

`make restart`, render the element live, confirm it looks right. Introspection
confirms the scene was received; a human eye confirms fidelity. Capture the
introspection snapshot (`inspect_scene`, `list_recent_events`) and get operator
confirmation before calling the element done.

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
