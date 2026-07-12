# Foundation audit — the 4 Element-ABC exemplars before element #5

**Status:** read-only audit. No code changed.
**Scope:** the 4 migrated Element-ABC kinds (`text`, `button`, `checkbox`,
`dialog`), their supporting machinery, roundtrip test coverage, and
introspection adequacy — the "harden the foundation" gate before Batch 1's
first kind (`progress`, element #5) crosses.
**Ground truth:** the code cited inline, plus
`docs/architecture/migration/README.md`,
`docs/architecture/migration/progress-element-design.md`, and the prior
`docs/architecture/element-migration-audit.md`.

This audit both confirms the two shipped inconsistencies the prior audit
flagged and finds that they are two faces of one larger fact: **`checkbox` is
uniformly half-migrated.** Its decode side flipped to the ABC path; its encode
side and its pump-side registration did not. `text` and `button` were
reconciled cleanly; `checkbox` was not.

---

## Executive summary

- The 4 exemplars share **one clean codec pattern** (per-kind
  `JsonXEncoder`/`JsonXDecoder` classes; thin `to_dict`/`from_dict` delegators
  on the element). The procedural-codec anti-pattern (`_<kind>_to_dict` module
  functions) is **absent** from all 4 — this is the corner the codebase got
  right, and it is the template `progress` must copy.
- But the 4 exemplars **diverge in three ways that compound per element**:
  duplicated boundary-validation helpers copied into every file; two different
  idioms for the same `from_dict` typing problem; and — most importantly —
  `checkbox` wired inconsistently across the encode/decode/pump dispatch tables.
- **`checkbox` is half-migrated (the headline finding).** It flipped on the
  decode side (`_ABC_KINDS`, `JsonCheckboxDecoder`) but was **never removed from
  the legacy `InputsRegistry`** (`inputs.py:48`) — unlike `text` and `button`,
  which were removed — and **never added** to `JsonEncoderFactory`
  (`encoder_factory.py`), to the `_element_to_dict` ABC tuple
  (`elements/__init__.py:185`), or to `_ABC_TYPES` (`domain_pump.py:32`). Its
  JSON encode works today only because it falls through to that un-removed
  legacy registration. The two "omissions" the prior audit flagged are coupled
  symptoms of this.
- **Two serialization paths exist, and the tests mostly exercise the wrong one
  for the exemplars.** The real Hub→Display wire for ABC elements is native
  **pickle** (`scene.py:78`–`:84`, `_pickled`), not the JSON codec. The JSON
  codec is a secondary surface (structural Protocol + `element_to_dict`
  introspection + agent `element_from_dict`). The "roundtrip" tests for
  `checkbox`/`button` route through pickle — so the checkbox encode asymmetry
  above is **untested**.
- **Two parallel Hub-side stores exist:** `Display` (`domain/display.py`, 440
  lines) and `HubDisplay` (`domain/hub/hub_display.py`, 398 lines). The live
  D21 path uses `HubDisplay`; the display-side dual-write pump uses `Display`.
  `Display.interact` is button-only (`display.py:325`, `:332`) and cannot
  dispatch the migrated `checkbox` — a stale parallel path inconsistent with
  the exemplar set.
- **The introspection primitive (`render_path` + `resolved_props`) is designed
  but not built.** Confirmed absent from `src/`. `inspect_scene` today returns
  only wire dicts from `SceneManager` and cannot assert ABC-vs-legacy,
  defaulted props, or Hub-authoritative post-interaction state.

### Must-fix before element #5

1. **Fully reconcile `checkbox`** (Batch 0). Remove it from `InputsRegistry`
   (`inputs.py:48`); add it to `JsonEncoderFactory.encode` (`encoder_factory.py`),
   to the `_element_to_dict` ABC tuple (`elements/__init__.py:185`), and to
   `_ABC_TYPES` (`domain_pump.py:32`). These four edits are coupled — doing any
   subset breaks JSON encode. This makes the exemplar set uniform before
   `progress` copies the pattern.
2. **De-duplicate the boundary validators** (`_str_or_raise` /
   `_opt_str_or_raise` / `_bool_or_raise`) now copied into all 4 files, before
   `progress` adds a 5th copy plus a new `_float_or_raise`.
3. **Build the `render_path` + `resolved_props` primitive** (progress-design §4)
   so #5's migration is verified programmatically, not by eye.

### Operator rulings needed before #5 (see §4)

- **R1** — ratify the `checkbox` reconciliation shape above (recommend proceed).
- **R2** — ratify the `Inspectable` Protocol + `DisplayServer.register_handler`
  placement for the primitive (progress-design §6 Q1/Q2; recommend ratify).
- **R3 (new)** — `hub_authoritative` semantics. As designed it reads the
  display-side `Display` mirror, **not** the Hub's `HubDisplay`. Decide: rename
  it honestly for #5 and defer real Hub-authority introspection to Batch 2, or
  build Hub-side introspection now. Recommend the former.
- **R4 (new)** — rule on the two-store duplication (`Display` vs `HubDisplay`)
  and the stale button-only `Display.interact`. Is `Display` vestigial
  (delete in Batch 7) or does it have a defined display-side role? This decides
  what `hub_authoritative` can even mean.

---

## 1. Tech-debt inventory

Ranked. Severity is impact × how much it compounds per future element.

### D1 — `checkbox` is half-migrated (HIGH; the root finding)

`text` and `button` were removed from the legacy codec registries when they
migrated (`basics.py:4` "text.py is registered separately"; `inputs.py:5`
"button.py is registered separately"). **`checkbox` was not** — it is still
registered in `InputsRegistry` (`inputs.py:48`–`:53`, pointing at
`CheckboxElement.to_dict`/`from_dict`). Meanwhile the decode side *was* flipped:
`checkbox` is in `_ABC_KINDS` (`element_factory.py:49`) and
`JsonElementFactory.decode` routes it to `_checkbox_decoder`
(`element_factory.py:124`).

Consequences, all confirmed:

- **Decode** goes through the ABC `JsonCheckboxDecoder`
  (`element_factory.py:182` short-circuits `_ABC_KINDS` before the codec table
  at `:190`). The `InputsRegistry` decode entry for checkbox is therefore dead
  for the factory path — a dual registration for one kind (violates the
  refactoring protocol's "never two live paths for the same kind").
- **Encode (JSON)** falls through to the legacy path: `checkbox` is **not** in
  the `_element_to_dict` ABC tuple (`elements/__init__.py:185`, which lists only
  `TextElement | ButtonElement | DialogElement`), so it hits the codec-table
  branch at `:188` plus the generic tooltip append at `:191`. It is **not** in
  `JsonEncoderFactory.encode` (`encoder_factory.py:36`–`:41`, Text/Button/Dialog
  only) — so `JsonEncoderFactory().encode(checkbox)` raises `TypeError`.
- **Pump** — `checkbox` is **not** in `_ABC_TYPES` (`domain_pump.py:32`,
  `(TextElement, ButtonElement, DialogElement)`), so an anonymous-id checkbox
  would fall to `dataclasses.replace` on an ABC instance (`domain_pump.py:136`)
  instead of raising the intended `ValueError` (`:129`). Latent (checkboxes
  carry explicit ids), but a real table-of-truth inconsistency.

**The trap:** "finishing" checkbox by removing it from `InputsRegistry` (to
match text/button) *without also* adding it to `JsonEncoderFactory` +
`_element_to_dict` breaks checkbox JSON encode. The four edits are one coupled
change.

**Fix (all four, one commit):** remove `inputs.py:48`–`:53`; add `checkbox` to
`encoder_factory.py` encode dispatch, to `elements/__init__.py:185`, and to
`domain_pump.py:32`. **Must-fix before #5** — the exemplar set must be uniform
before it is used as a copy template.

### D2 — Duplicated boundary validators across all 4 files (HIGH; compounds per element)

`_str_or_raise` and `_opt_str_or_raise` are copy-pasted static methods in
`text.py:126`–`:140`, `button.py:138`–`:152`, `checkbox.py:106`–`:120`,
`dialog.py:233`–`:247`. `_bool_or_raise` is duplicated in `button.py:154`–`:160`
and `checkbox.py:122`–`:128`. Four near-identical copies of the same PY-EH-1
coercion logic. `progress` (§#5) adds a 5th copy plus a new `_float_or_raise`.

This is exactly the divergence the audit is meant to weight: a per-element
multiplier. Per PY-IC-1 / PY-OO-7, these belong in one shared surface — the
decode path already has the equivalent coercers on `ElementWireContext`
(`require_str`, `optional_nullable_str`, `optional_bool`, used in every
`*_codec.py`), so the setter path is re-implementing what the decode path
already owns.

**Fix:** extract one shared boundary-coercion surface (a small typed helper, or
reuse `ElementWireContext`) that all `_set_<field>` setters call. **Must-fix
before #5** — or, at the latest, done *within* the #5 PR so `progress` reuses
rather than copies. Recommend before #5 so #5 is a clean copy.

### D3 — Two parallel Hub-side stores; one is stale (HIGH strategic; needs R4)

`domain/display.py` defines `Display` (440 lines); `domain/hub/hub_display.py`
defines `HubDisplay` (398 lines). Both docstrings claim "authoritative."

- **Live D21 dispatch** resolves from `HubDisplay` (`clients.py:129`–`:130`,
  the `hub_display` singleton) and supports both `ButtonClicked` and
  `ValueChanged` (`clients.py:157`–`:194`).
- **Display-side dual-write pump** writes into `Display`
  (`domain_pump.py:10`, `server.py:172`–`:175`).
- **`Display.interact` is button-only.** `_build_event` (`display.py:325`,
  `:332`) raises `WrongKindError` for any non-button kind and for
  `value is not True`. So the migrated `checkbox` — a shipped ABC exemplar —
  **cannot** be dispatched through `Display.interact`, even though the live path
  (`HubDisplay`) handles it. `Display.interact` is a stale parallel
  implementation inconsistent with the exemplar set.

This duplication also undercuts the introspection design (see §3): the proposed
`hub_authoritative` field reads the display-side `Display` mirror, not the true
Hub `HubDisplay`.

**Fix:** operator ruling (R4) on whether `Display` is vestigial (retire with the
legacy path in Batch 7) or has a defined display-side-mirror role. If it stays,
either wire `Display.interact` to the two-tier event set or delete the dead
button-only path. Not blocking #5's mechanics, but the ruling gates the
`hub_authoritative` semantics #5's introspection depends on.

### D4 — `from_dict` idiom divergence (MED; the "each does it differently" smell)

The 4 exemplars solve the same `from_dict` DI-wiring problem three ways:

- `text.py:164` — constructs the decoder inline, no handlers, clean.
- `button.py:203` — top-level imports; `cast("PublishSink", RaisingPublishSink(...))`.
- `checkbox.py:151`–`:165` — **inline** imports with `# noqa: PLC0415`, and
  `# type: ignore[arg-type]` instead of `cast` for the identical sink-typing
  problem button solved with `cast`.
- `dialog.py:275` — top-level imports; `cast`.

Two import placements (top vs inline) and two type-narrowing idioms
(`cast` vs `type: ignore`) for one problem. **Fix:** make `checkbox` match
`button` (top-level imports, `cast`). MED — cosmetic, but it is the precise
kind of per-exemplar divergence that compounds. Bundle with D1's checkbox work.

### D5 — `checkbox.widget_value()` legacy wart (MED; Decision (c) territory)

`checkbox.py:168`–`:170` carries a `widget_value()` method no other exemplar
has — a `SceneManager` `WidgetState`-mirror coupling from the legacy path. It is
a legacy-path residue on an otherwise-migrated element. Not blocking #5
(`progress` is display-only, no widget value). Resolve when the interactive
`WidgetState` authority question (audit Decision (c)) is settled in Batch 2.

### D6 — Wrap seam imports its own subclasses (MED; before Batch 2, not #5)

`Element.wrap_handlers_for_remote` imports `ButtonElement` and `CheckboxElement`
inside the method (`element_abc.py:228`–`:229`) and branches on `isinstance`
(`:231`, `:248`). A base class importing its concrete subclasses is a layering
inversion (PY-IC-7 / PY-IC-8). This is the ratified Decision (e) / README
decision 5 (invert the seam). It is a **prerequisite for Batch 2 (interactive
inputs)**, not for #5 — `progress` is a display-only leaf and matches neither
branch. Flag as scheduled; do not do it in the #5 PR.

### D7 — `element_abc.py` over the module-size target (LOW)

`element_abc.py` is 321 lines (PY-OO-2 target ≤ 300). `display.py` (440) and
`hub_display.py` (398) are also over, but they are supporting machinery, not the
4 exemplar element modules. Refactor-track debt; not blocking. (If D3/R4 retires
`Display`, that pressure resolves itself.)

### D8 — Stale docstrings (LOW)

`element_factory.py:6` and `:58`–`:60` say "Text, Button, Dialog," omitting
`checkbox`, though the code includes it (`_ABC_KINDS`, decode dispatch).
`domain_pump.py:41`–`:46` lists the native kinds prose-style. Cosmetic; fix when
touching the files for D1.

### What is NOT debt (the clean parts, for the record)

- **The codec pattern is right.** All 4 exemplars use per-kind
  `JsonXEncoder`/`JsonXDecoder` classes (`text_codec.py`, `button_codec.py`,
  `checkbox_codec.py`, `dialog_codec.py`) with `to_dict`/`from_dict` as ≤3-line
  delegators on the element. The procedural `_<kind>_to_dict` module-function
  anti-pattern is **absent** from all 4. This is the exemplar to copy.
- **`id`/`kind`/setter/`apply_patch` shapes are consistent** across the 4:
  private `_id`/`_kind`, read-only properties, inherited `apply_patch`
  (`element_abc.py:124`) dispatching to `_set_<field>`. Dialog correctly
  overrides `_children()` (`dialog.py:215`) as the composite exemplar.
- **Module sizes for the element files are within/near target**: `text.py` 173,
  `button.py` 211, `checkbox.py` 170, `dialog.py` 283.

---

## 2. Roundtrip test coverage

### The load-bearing fact: two serialization paths

The real Hub→Display wire for ABC elements is **native pickle**, not the JSON
codec. `_scene_to_dict` (`scene.py:78`–`:84`) pickles every `AbcElement` into
`{"_pickled": base64(...)}`; `_scene_from_dict` (`scene.py:122`–`:127`)
unpickles. The JSON codec (`to_dict`/`from_dict`, `JsonXEncoder`/`Decoder`) is a
**secondary** surface: it satisfies the structural `domain.element.Element`
Protocol, feeds `element_to_dict` (introspection), and backs the agent-side
`element_from_dict`. It is **not** the transport for the 4 exemplars inside a
`SceneMessage`.

This matters because the "roundtrip" tests for the ABC kinds mostly exercise the
**pickle** path, not the JSON codec — `test_button_disabled_included`
(`test_protocol.py:779`–`:789`) asserts `"_pickled" in d["elements"][0]`.

### Per kind

| Kind | Wire (pickle) scene roundtrip | JSON codec roundtrip | Hub-side D21 dispatch |
|------|---|---|---|
| `text` | Yes — `test_protocol.py:1282`, `:1293` (assert `_pickled` restore) | Partial — isolated `ElementCodec` roundtrip `:1980`–`:1997`; no direct `to_dict`→`from_dict` value assertion | n/a (display-only) |
| `button` | Yes — `:779`–`:800` (disabled true/false restore) | Yes — `element_from_dict` arrow/small/backwards-compat `:1504`–`:1522` | Yes (hand-fed) — `test_hub_interaction_dispatch.py:22`–`:70` |
| `checkbox` | Yes — `test_checkbox_roundtrip` `:829`–`:837` | **Gap** — no direct `element_from_dict`/`to_dict` test; the D1 encode asymmetry is **untested** (tests use pickle) | Yes (hand-fed) — `test_hub_interaction_dispatch.py:203`–`:245` |
| `dialog` | **Gap** — no explicit dialog scene pickle roundtrip in `test_protocol.py` | Via regression only — `test_dialog_interaction_trace.py:412` (`element_from_dict`) | Partial — the dialog dismiss/re-push cascade is in the regression trace, not a focused crossing test |

### The boundary-stub concern (the failure mode the display_lifecycle audit caught)

`test_hub_interaction_dispatch.py` genuinely exercises the **Hub half** of the
crossing: a real `HubDisplay()`, real `element.fire`, handlers run exactly once
(`:65`–`:68`), a real `apply_patch` mutation for checkbox, and a real re-push
(asserted via a `MagicMock` client, `:69`–`:70`, `:244`–`:245`). That is real
Hub-side behavior, not a stub.

**But the Display→wire→Hub leg is stubbed.** The `RemoteEventHandlerInvocation`
is **hand-constructed** in every test (`:55`–`:63`, `:232`–`:241`), not produced
by the Display's `wrap_handlers_for_remote` → `RemoteDispatchGroup` → socket
send path. `hub_display` and `client_registry` are monkeypatched; the
`DisplayClient` is a `MagicMock`. So no test drives the *full* loop where a
Display-side wrapped handler emits the invocation the Hub then consumes.

### Plain verdict

- **`text`** — genuine wire (pickle) roundtrip: **yes**. JSON codec value
  roundtrip: **partial**.
- **`button`** — genuine wire roundtrip: **yes**. JSON decode: **yes**. Hub-side
  click dispatch: **yes**, but with a hand-fed invocation.
- **`checkbox`** — genuine wire roundtrip: **yes**. The JSON-encode asymmetry
  (D1) is **untested** because the wire path is pickle. Hub-side value_changed
  dispatch: **yes**, hand-fed.
- **`dialog`** — Hub-side dispatch + `mark_removed` cascade + re-push: **partial**
  (regression trace). Explicit scene serialization roundtrip: **missing**.
- **None of the 4** exercise the full Display-produced-invocation → socket → Hub
  leg. Every crossing test injects the invocation directly — the boundary-stub
  pattern the earlier coverage audit warned about.

### Roundtrip tests to add (before / alongside #5)

1. A **checkbox JSON-encode** test that would catch D1 — `element_to_dict(cb)`
   emits `tooltip` exactly once and does not raise. (Add now; it is the missing
   guard for the reconciliation.)
2. A **dialog scene serialization** roundtrip (pickle path) mirroring
   `test_button_disabled_included`.
3. At least one **end-to-end crossing** test where `wrap_handlers_for_remote`
   produces the `RemoteEventHandlerInvocation` that the Hub consumes — closing
   the hand-fed-invocation gap for at least the button exemplar, so Batch 2
   inherits a real end-to-end template.
4. For #5: the `progress` protocol roundtrip **plus** a `resolved_props`
   default-reads-back assertion (progress-design §5.1 items 3, 6).

---

## 3. Introspection adequacy

### What `inspect_scene` returns today

`QueryDispatcher._query_inspect_scene` (`query_dispatcher.py:98`–`:109`) returns
exactly:

```json
{ "scene_id": "...", "elements": [ /* element_to_dict(e) per element */ ] }
```

It reads **only** `SceneManager` (`query_dispatcher.py:102`). It runs on the
**display** process. Nothing else is exposed — no render path, no resolved
props, no domain-store read.

### Can it assert, without pixels…

- **(a) ABC path vs legacy?** **No.** `element_to_dict` returns the wire dict;
  nothing surfaces the element object's Python type or a `render_path`.
- **(b) Resolved props read back?** **No.** The JSON encoders `strip_none` and
  omit defaults (`text_codec.py:100`; checkbox/button similarly), so a test
  cannot assert `label == ""` or `tooltip is None` *reads back* — the wire dict
  simply lacks the key.
- **(c) D21 fired the real Hub handler and mutated authoritative state?** **No —
  and it is structurally harder than the design assumes.** The authoritative
  post-interaction state lives in **`HubDisplay`** (luxd process).
  `inspect_scene` runs on the **display** process and reads `SceneManager`; it
  cannot see `HubDisplay`. Even the display-side `Display` mirror
  (`server.py:172` `_domain_display`) is a *different* store from the Hub's
  `HubDisplay` (see D3).

### The proposed primitive (progress-design §4)

`render_path` + `resolved_props` via an `Inspectable` Protocol
(`resolved_props() -> Mapping[str, object]`), serialized through typed
`ElementInspection`/`SceneInspection` value classes, registered on
`DisplayServer` via `qd.register_handler("inspect_scene", ...)`.

- **Built?** **No.** Confirmed: `render_path`, `resolved_props`,
  `element_paths`, `Inspectable`, `ElementInspection`, `SceneInspection` are
  **absent** from `src/`. Designed only.
- **Right design for (a) and (b)?** **Yes.** `render_path` by
  `isinstance(elem, ElementABC)` is a sound query-side boundary decision;
  `resolved_props` via a single-method runtime-checkable Protocol (PY-DP-11,
  PY-TS-10) lets each kind opt in without widening the ABC. It scales one kind
  per migration. This is the correct primitive and should ship in the #5 PR.
- **The gap the design under-addresses — (c).** The proposed
  `hub_authoritative` field is computed from the **display-side `Display`
  mirror** (`domain_display.snapshot(...)`, progress-design §4.2), **not** from
  the Hub's `HubDisplay`. So `hub_authoritative == True` actually means "the
  display-side dual-write pump accepted this element into the display's `Display`
  mirror" — **not** "this element is authoritative in the Hub." The name
  over-promises. For a display-only leaf like `progress` this does not bite
  (there is no interaction to verify), but for the interactive kinds (Batch 2+),
  verifying "the D21 interaction fired the real Hub handler and mutated
  authoritative state" requires introspection into `HubDisplay` (luxd side),
  which **no current API reaches**. The `test_hub_interaction_dispatch` pattern
  (monkeypatched `HubDisplay` + `MagicMock`) is a unit test, not live
  introspection.

### What introspection MUST exist before #5

- **`render_path` (`abc`|`legacy`) + `resolved_props`** in `inspect_scene` — the
  §4 primitive. **Required, not built.** Build it in the #5 PR (as designed) so
  `progress` is verified programmatically (flip reads `"abc"`, `fraction`/`label`
  read back including defaults).
- **An honest name/scope for `hub_authoritative`** (R3). Either rename it to
  reflect the display-side-mirror truth (e.g., `domain_mirror_present`) and
  scope #5's assertion to that, or defer the field until Hub-side introspection
  exists. `progress` does not need Hub-authority verification, so the honest
  narrow field is sufficient for #5.

### What must exist before the first interactive migration (Batch 2, not #5)

A **Hub-side introspection surface** that reads `HubDisplay` so a test can assert
post-click authoritative state (handler fired, state mutated) without
monkeypatching a stand-in store. Flag now; not blocking #5.

---

## 4. Prioritized action list

### Must eliminate / build before element #5

1. **[D1] Fully reconcile `checkbox`** (one coupled commit): remove from
   `InputsRegistry` (`inputs.py:48`–`:53`); add to `JsonEncoderFactory.encode`
   (`encoder_factory.py:36`+), to `_element_to_dict` ABC tuple
   (`elements/__init__.py:185`), and to `_ABC_TYPES` (`domain_pump.py:32`).
2. **[D2] De-duplicate boundary validators** shared by all `_set_<field>`
   setters, so `progress` reuses instead of adding a 5th copy.
3. **[Tests] Add the checkbox JSON-encode guard** (catches D1) and a **dialog
   scene serialization** roundtrip.
4. **[Introspection] Build `render_path` + `resolved_props`** (progress-design
   §4) in the #5 PR.
5. **[D4] Unify `checkbox.from_dict`** with the `button` idiom (bundle with #1).

### Operator rulings needed before #5

- **R1** — ratify the D1 checkbox reconciliation shape. *Recommend proceed.*
- **R2** — ratify `Inspectable` Protocol + `DisplayServer.register_handler`
  placement (progress-design §6 Q1/Q2). *Recommend ratify.*
- **R3 (new)** — `hub_authoritative` semantics: rename to reflect the
  display-side `Display` mirror for #5 and defer real Hub-authority
  introspection to Batch 2, **or** build Hub-side introspection now. *Recommend
  rename + defer* (#5 is display-only).
- **R4 (new)** — rule on the `Display` vs `HubDisplay` duplication and the stale
  button-only `Display.interact`: vestigial (retire in Batch 7) or a defined
  display-side role? This gates what `hub_authoritative` can mean.

### Can wait (schedule, do not block #5)

- **[D3/R4] Two-store dedup mechanics** — after the R4 ruling; delete or wire
  `Display.interact`'s dead button-only path.
- **[D5] `checkbox.widget_value()`** — resolve with the `WidgetState` authority
  question (audit Decision (c)) in Batch 2.
- **[D6] Wrap-seam inversion** (`element_abc.py:228`–`:264`) — prerequisite for
  **Batch 2**, not #5.
- **[D7] Module-size** of `element_abc.py` (321) / `display.py` (440) /
  `hub_display.py` (398) — refactor track.
- **[D8] Stale docstrings** — fix when touching the files for D1.
- **[Introspection] Hub-side introspection surface** reading `HubDisplay` —
  before the first interactive migration (Batch 2).

---

## 5. Report status

Read-only audit. No code changed. Saved to
`docs/architecture/migration/foundation-audit.md`.
