# Foundation Exemplar Hardening — Review R2

Branch: `fix/foundation-exemplar-hardening` (7 commits ahead of `origin/main`).
Scope (identical to R1): the 4 Element-ABC exemplars (text/button/checkbox/
dialog), the shared modules (`patch_field.py`, `abc_di_defaults.py`), the
introspection primitive (`inspectable.py`, `scene_inspection.py`,
`scene_inspector.py` + DisplayServer wiring), the `Display.interact` checkbox
fix, and the new tests.

Method: re-derived fresh from the current tree — I did not trust R1's report.
Read the full `origin/main..HEAD` diff, every changed/new source and test file
end to end, `tests/CLAUDE.md` Levels 1–5, and the two Round-2 commits (`e242743`,
`43da761`). Ran `make check`.

## Verdict

**ZERO high-confidence blocking defects in the foundation.** The two R1 items are
genuinely cleared and introduced no new debt. The four exemplars are structurally
identical in the required shape; the shared modules are shared everywhere; the
introspection primitive is honest and correct; `Display.interact` dispatches both
tiers; every new test exercises the real boundary with failure-path coverage; OO
rules hold on every touched/new file. The copy-template is clean — element #5 can
copy `text.py` verbatim in shape and inherit nothing warty.

One **informational** note follows about drift in element #5's *unratified design
doc* (outside this branch's diff). It is not a foundation defect and does not
block clearing element #5; it is flagged only so the #5 implementer is not misled
by a stale sentence.

### `make check` result

```text
oo_score --check      No Python files touched -- trivial pass
suppression ratchet   PASS (122 unchanged)
ruff check            All checks passed
ruff format --check   270 files already formatted
markdownlint          0 errors
skill-permissions     in sync
mypy src/ tests/      Success: no issues found in 263 source files
pyright src/ tests/   0 errors, 0 warnings, 0 informations
pytest                1442 passed, 18 deselected
```

(1438 → 1442 = the +4 parametrized cases of the new guardrail test; no test lost.)

## R1 item 1 — dead-in-prod `_query_inspect_scene` removed (commit `e242743`)

**CONFIRMED cleared, no dangling reference, covered end-to-end.**

- No production path lost its `inspect_scene` handler. `DisplayServer.__new__` is
  the sole production `QueryDispatcher(...)` caller (`display/server.py:206`;
  grep-confirmed unique in `src/`) and it registers the enriched handler
  unconditionally: `qd.register_handler("inspect_scene", self._scene_inspector.inspect)`
  (`display/server.py:277`). Both production readers route through it:
  - the socket introspect path `_handle_introspect` →
    `handle_query("inspect_scene", …)` (`display/server.py:719`), which reads
    `qr.result["elements"]` — the key `SceneInspection.to_dict` still emits
    (`scene_inspection.py:144`);
  - the MCP tool `inspect_scene` → `client.query("inspect_scene", …)`
    (`tools/tools.py:601`).
- No dangling import/reference. `_query_inspect_scene` and the unused
  `element_to_dict` import were both removed from `query_dispatcher.py`; the
  `_query_handlers` dict (`query_dispatcher.py:48-54`) no longer self-registers
  `inspect_scene`. Grep for `_query_inspect_scene` across `src/` and `tests/` is
  empty.
- Covered end-to-end through the real `DisplayServer` + `QueryDispatcher`:
  `test_scene_inspection.py::test_inspect_scene_*` feed a scene via
  `server._handle_message(...)` then call
  `server.query_dispatcher.handle_query("inspect_scene", …)` — the registered
  handler, not a mock. The unknown-scene case asserts `error` surfaces (PY-EH-8),
  not a blank.
- R1 also flagged the duplicated `{scene_id, elements:[...]}` serialization. With
  the built-in deleted there is now exactly one implementation
  (`SceneInspection.to_dict`). Duplication resolved.
- No new debt. The rebaseline note (`avg_params 1.45→1.50`) is a mechanical
  artifact of deleting a low-param method; `avg_complexity 2.27→2.20` and
  `module_size 181→168` improved. Deleting a dead-in-prod handler is the correct
  action; the mean-param uptick is inherent and documented, not a quality
  regression.

## R1 item 2 — `resolved_props` coverage guardrail added (commit `43da761`)

**CONFIRMED structural, correctly directed (⊆), and genuinely failing on omission.**

`test_scene_inspection.py::test_resolved_props_covers_the_settable_surface`
(`:132`):

- **Structural, not hardcoded.** Expected keys are derived from each element's own
  surface: `_constructor_prop_fields` reads the keyword-only constructor params
  minus the DI sentinels + identity (`{renderer_factory, emit, id}`, `:105`);
  `_setter_fields` reads the `_set_<field>` method names off `dir(cls)` (`:117`).
  Union = the settable surface. No literal key list.
- **Coverage (⊆) assertion is correct.** `missing = settable - resolved; assert
  not missing` asserts `settable ⊆ resolved` — every settable field must appear in
  `resolved_props`, while derived-only props may exceed it. Dialog reports
  model-derived `visible`/`confirmed` (no `_set_*`, not constructor params), so
  they are correctly outside `settable` and allowed as surplus. Verified by hand
  for all four: text/button/checkbox settable == resolved; dialog settable
  `{title, tooltip}` ⊂ resolved `{title, visible, confirmed, tooltip}`.
- **Genuinely fails on omission.** If a future kind adds `_set_foo` or a
  constructor prop `foo` and omits it from `resolved_props`, `foo ∈ settable` and
  `foo ∉ resolved`, so `missing = {foo}` and the assert fires. The derivation is
  sound because the `Element` ABC defines **no** `_set_*` methods of its own
  (grep-confirmed; `apply_patch` dispatches to subclass `_set_<key>` via `getattr`,
  `element_abc.py:144`), so `dir(cls)` picks up only the subclass's real setters —
  no spurious inherited requirement.

## Foundation re-judgment (fresh)

- **Exemplar structural identity.** Re-read all four. Identical section order:
  module docstring (with PY-TS-14 notes) → attribute annotations → `__new__`
  (keyword-only, sentinel defaults, `super().__new__(cls, renderer_factory=…,
  emit=…)`) → read-only `@property` accessors → `_set_<field>` setters coercing
  through `PatchField(...).as_*` → `to_dict`/`from_dict` ≤3-line delegators →
  `resolved_props`. Per-kind differences are all legitimate: `text` has no
  `handler_decoder` and no `widget_value` (correct non-interactive template);
  `button`/`checkbox` inject a `handler_decoder`; `checkbox` adds `widget_value`
  and an `action: Literal["changed"]`; `dialog` composes `DialogModel`, injects a
  `publish_sink`, and exposes `install_children`/`_children`. No divergence.
- **Shared modules genuinely shared.** `PatchField` is called from every `_set_*`
  in all four; `NO_EMIT`/`RAISING_FACTORY` are the `__new__` defaults in all four.
  `test_the_four_exemplars_no_longer_define_local_coercers` walks each AST and
  asserts zero leftover `_*_or_raise`; `test_exemplars_construct_with_the_shared_
  sentinels` proves each directly-constructed element carries `RAISING_FACTORY`.
- **Introspection primitive honest and correct.** `Inspectable` is a
  `runtime_checkable` single-method Protocol (PY-DP-11), resolved via `isinstance`
  (PY-TS-10, no `hasattr`). `ElementInspection.from_element` classifies
  `render_path` via `isinstance(ElementABC)` and picks `resolved_props` via
  `isinstance(Inspectable)` with an `element_to_dict` legacy fallback.
  `SceneInspector.inspect` raises `LookupError` on a missing scene (PY-EH-8) and
  `_mirror_ids` honestly documents its per-scene all-or-nothing routing.
  DisplayServer wiring declares `_scene_inspector` and constructs it with the real
  `SceneManager` + domain `Display`.
- **`Display.interact` two-tier.** `_build_event` constructs `ButtonClicked` for a
  button and `ValueChanged` for a checkbox — the same two-tier event set the live
  Hub dispatch builds — and raises `WrongKindError` otherwise; `interact` fires it
  on the resolved ABC element exactly once. The class docstring documents the
  display-mirror vs `HubDisplay` distinction and that `interact` is the in-process
  dispatch contract. Failure paths covered
  (`test_interact_checkbox_rejects_non_bool_value`).
- **Tests exercise the real boundary (Levels 1–5).** L1/L2:
  `test_abc_wire_roundtrip.py` ships all four through the real `SceneMessage`
  wire, asserts `_pickled` present, and adds the dialog + dialog-with-child scene
  roundtrips. L4: `test_full_wrap_socket_hub_leg_fires_once_on_authoritative_copy`
  drives a real `socket.socketpair`, the invocation comes from
  `wrap_handlers_for_remote` (never hand-built), the Hub fires once and the
  display-side handler `pytest.fail`s if it runs locally — now on the reconciled
  `CheckboxElement`. L5: the enriched handler is driven through a live
  `DisplayServer`. The only `MagicMock` is the socket (`_mock_sock`), not the
  handler under test.
- **OO compliance.** `__new__` everywhere (PY-CC-1); underscore-prefixed state
  (PY-EN-1); `Literal` discriminators and `RenderPath = Literal["abc","legacy"]`;
  each residual `| None` carries a PY-TS-14 justification; `Inspectable` is a
  Protocol not a base class; `SceneInspector`/`DialogElement` compose rather than
  inherit.

## Informational (non-blocking, outside this branch's diff)

`docs/architecture/migration/progress-element-design.md:383-384` — element #5's
(unratified) design proposal states the built-in `inspect_scene` in
`QueryDispatcher` "stays as the no-domain-Display fallback." Commit `e242743`
deleted that built-in, so the sentence is now stale; the doc also names the
handler `_query_inspect_scene_enriched` and the prop `hub_authoritative`, whereas
the shipped foundation named them `SceneInspector.inspect` and
`domain_mirror_present`. This file is not in the branch diff and is explicitly a
proposal with open operator questions (§6 Q1/Q2), so it is not a foundation
defect — it will be reconciled when element #5 is designed against current
reality. Flagged only so the #5 implementer does not rely on a fallback that no
longer exists.

## Bottom line

The reviewed foundation — exemplars, shared modules, introspection primitive,
`Display.interact`, and tests — has **zero high-confidence defects**. Both R1
items are cleared without introducing new debt, and `make check` is green. This
verdict clears element #5 to be built on these exemplars.
