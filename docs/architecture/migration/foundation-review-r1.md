# Foundation Exemplar Hardening — Review R1

Branch: `fix/foundation-exemplar-hardening` (5 commits ahead of `origin/main`).
Scope: the 4 Element-ABC exemplars (text/button/checkbox/dialog), the new shared
modules (`patch_field.py`, `abc_di_defaults.py`), the introspection primitive
(`inspectable.py`, `scene_inspection.py`, `scene_inspector.py` + DisplayServer
wiring), the `Display.interact` checkbox fix, and the five new test files.

Method: re-derived from the current tree, not from the prior audit. Read the full
`origin/main..HEAD` diff, every changed source file end to end, the five new test
files, and `tests/CLAUDE.md` §"Round-trip test procedure". Ran `make check`.

## Verdict

**No high-confidence blocking defect.** The four exemplars are now structurally
identical in the required shape, the shared modules are genuinely shared
everywhere (grep-confirmed: zero lingering private coercers or per-file
sentinels), the tests exercise the real boundaries per Levels 1–5 with
failure-path coverage, and `make check` is green (mypy 0, pyright 0, ruff clean,
1438 passed).

The exemplar **copy-template is clean** — element #5 (a non-interactive kind like
`progress`) can copy `text.py` verbatim in shape and inherit nothing warty.

Three findings follow. None is a functional bug; none lives in the exemplar
template. The top one is a LOW structural smell in the introspection *wiring*;
the other two are informational guardrail notes. I am **+0** on whether the
top finding must be cleared before element #5 — it does not propagate to the
template — but it is a real, concrete cleanup and I recommend taking it now.

## `make check` result

```text
oo_score --check      No Python files touched -- trivial pass
suppression ratchet   PASS (122 unchanged)
ruff check            All checks passed
ruff format --check   270 files already formatted
markdownlint          0 errors
mypy src/ tests/      Success: no issues found in 263 source files
pyright src/ tests/   0 errors, 0 warnings, 0 informations
pytest                1438 passed, 18 deselected
```

## Structural identity of the four exemplars

Confirmed identical section order and shape across text/button/checkbox/dialog:

1. module docstring naming the shared DI sentinels and the codec split;
2. `__new__(*, renderer_factory=RAISING_FACTORY, emit=NO_EMIT, id, ...)` →
   `super().__new__(cls, renderer_factory=..., emit=...)`;
3. read-only `@property` accessors (`id`, `kind`, then the wire-facing fields);
4. `_set_<field>` setters that coerce through `PatchField(...).as_*` (PY-EH-1);
5. `to_dict` / `from_dict` ≤ 3-line codec delegators;
6. `resolved_props()` returning the full resolved state including defaults.

The remaining per-kind differences are all *legitimate*, not divergence:

- `text` has no `handler_decoder` in `from_dict` and no `widget_value` — it is
  non-interactive. This is the correct template for a non-interactive element #5.
- `checkbox` adds `widget_value()` (value mirror into `WidgetState`); `button`
  and `checkbox` inject a `handler_decoder`; `dialog` injects a `publish_sink`
  and is a composite (`DialogModel`, `install_children`, `_children`). Each
  difference tracks a real capability difference, not template drift.

`apply_patch` (id/render/patch mechanics) is inherited from the `Element` ABC in
all four — the copy-template surface a new kind must supply is exactly items 1–6
above. That surface is uniform.

## Findings

### 1. LOW — built-in `inspect_scene` handler is now shadowed in production and untested; its elements-array serialization is duplicated

- `src/punt_lux/display/server.py:277` —
  `qd.register_handler("inspect_scene", self._scene_inspector.inspect)` overrides
  the key the dispatcher self-registers at
  `src/punt_lux/query_dispatcher.py:49` (`"inspect_scene": self._query_inspect_scene`).
- `DisplayServer.__new__` is the only production `QueryDispatcher(...)` caller
  (`server.py:206`), and it always installs the override. So
  `QueryDispatcher._query_inspect_scene` (`query_dispatcher.py:98-109`) is
  unreachable in production.
- No test exercises the built-in standalone: `tests/test_query_dispatcher.py`
  registers its own dummy handler and never queries `inspect_scene`; every other
  `inspect_scene` test drives the enriched path or mocks `client.query`. So the
  built-in is dead-in-prod *and* uncovered.
- Its body — `{"scene_id": ..., "elements": [element_to_dict(e) ...]}` — is
  re-implemented by `SceneInspection.to_dict` (`scene_inspection.py:140-151`),
  which the review calls out as "byte-for-byte" the same `elements` list. Two
  implementations of one wire shape.

This is genuine debt introduced by commit `035d53d` (the override is new). It
does **not** touch the exemplar template and does **not** multiply with
element #5 (adding a kind registers no new handler). Behavior is correct today.

Concrete fix: make `SceneInspector` the sole `inspect_scene` handler. Remove
`_query_inspect_scene` and its `_query_handlers` entry from `QueryDispatcher`;
`DisplayServer` already registers the enriched inspector unconditionally. If a
standalone (non-DisplayServer) default is wanted, keep exactly one implementation
and have the other delegate to it — do not keep two. Add a
`test_query_dispatcher` case for whichever survives so it is covered.

### 2. INFORMATIONAL — `resolved_props` has no structural guardrail; a future kind can silently omit a field

`resolved_props` is a hand-maintained dict on each class (e.g.
`checkbox.py:150-156`). The four exemplars are complete, but nothing asserts that
a kind's `resolved_props` keys cover its constructor/`_set_*` state surface. The
Level-5 tests assert exact dicts for the *migrated* kinds, so they would only
catch a regression if the author also updates the assertion. When element #5
copies the template, an omitted field in `resolved_props` would pass every gate.

Suggestion (not required to ship this branch): add one parametrized test that,
for each migrated kind, asserts `set(resolved_props()) == {the settable/state
fields}` (or is a superset of the `_set_*` targets). This converts the invariant
from "reviewer remembers" to "gate enforces" before the pattern is copied N more
times.

### 3. INFORMATIONAL — `domain_mirror_present` is a per-scene all-or-nothing signal exposed per-element

`SceneInspector._mirror_ids` (`scene_inspector.py:47-58`) returns an empty set
whenever the display pump skipped the scene, which it does for any scene
containing a non-native kind. So in a *mixed* scene, a migrated ABC element that
is genuinely on the abc render path still reports `domain_mirror_present: False`.
The name reads as a per-element fact; the value is really "did the pump route
this whole scene".

This is documented honestly in both `scene_inspection.py:38-46` and the
`_mirror_ids` docstring, and Level 5 explicitly scopes it ("do not assert Hub
authority from the display side"). No change required. Flagging only so the
element-#5 verifier does not read `domain_mirror_present: False` on a mixed scene
as a migration failure — verify mirror presence on an all-native scene, as
`test_inspect_scene_reports_domain_mirror_presence_for_native_scene` does.

## Test-quality assessment (against tests/CLAUDE.md Levels 1–5)

Real boundaries, no stubbing of the thing under test:

- **Level 1/2** — `test_abc_wire_roundtrip.py` ships all four kinds through the
  real `SceneMessage` wire, asserts the `_pickled` entry is present (the ABC wire
  form, the exact surface the checkbox half-migration missed), and now covers the
  dialog scene roundtrip and a dialog-with-child that previously had none.
- **Level 4** — `test_full_wrap_socket_hub_leg_fires_once_on_authoritative_copy`
  does not hand-build the `RemoteEventHandlerInvocation` (it comes from
  `wrap_handlers_for_remote`), crosses a real `socket.socketpair` via production
  framing, and asserts the Hub fires the real handler exactly once while the
  display-side handler `pytest.fail`s if it runs locally. This is the genuine D21
  leg, not a MagicMock.
- **Level 5** — `test_scene_inspection.py` drives the enriched `inspect_scene`
  through a live `DisplayServer._handle_message` + `QueryDispatcher.handle_query`,
  asserts `render_path` abc-vs-legacy against a real ProgressElement control, and
  asserts `resolved_props` reads back stripped defaults (`value=False`,
  `label=""`). The unknown-scene case asserts `error` is surfaced, not a blank
  (PY-EH-8).
- **Failure paths** — `test_interact_checkbox_rejects_non_bool_value`,
  `test_patch_field.py::test_as_bool_rejects_int_one` (guards the `1 is not True`
  boundary), and the non-button/checkbox `WrongKindError` control are present.
- **Dedup is proven, not asserted by comment** —
  `test_the_four_exemplars_no_longer_define_local_coercers` walks each exemplar's
  AST for leftover `_*_or_raise` methods; grep across `src/` confirms zero
  lingering `_str_or_raise` / `_no_emit` / per-file `RaisingRendererFactory()`.

No vacuous introspection assertions found; no kind is missing a wire roundtrip.

## Bottom line

The foundation is a clean copy-template for element #5. Finding #1 is a real but
isolated cleanup in the introspection wiring (not the template); findings #2
and #3 are guardrail/verification notes. If the operator's bar is "the exemplars and
shared modules are exemplary and identical in shape" — that bar is met. If the
bar extends to "zero dead-in-prod handlers introduced by this branch" — clear
finding #1 first.
