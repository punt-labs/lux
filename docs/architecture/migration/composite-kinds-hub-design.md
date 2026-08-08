# Composite Kinds and Hub Authority — Design and Correction

**Status:** design, no code changes. Grounded in `target.md`,
`element-contract.md`, `ui-model.md`, and the code cited inline.

**Point-in-time note:** §1's code citations to `_BASICS_KINDS`,
`_INPUTS_KINDS`, `_COMPOSITE_KINDS`, `_NATIVE_KINDS`, and
`src/punt_lux/display/domain_pump.py` describe the tree as it stood when
this investigation ran. This document's own §5 Q1 recommended deleting that
wiring outright; a later PR in the same epic executed that recommendation,
so those symbols and that file no longer exist on `main`. Read §1 as the
diagnosis that justified the deletion, not as a description of the current
tree.

## 1. Restated problem, and what investigation found

The assignment describes a gap: only 16 of 25 element kinds
(`_BASICS_KINDS` + `_INPUTS_KINDS` + `_COMPOSITE_KINDS` in
`src/punt_lux/display/server.py:92`–`115`) appear in `_NATIVE_KINDS`, the set
`DomainPump.route` (`src/punt_lux/display/domain_pump.py:90`–`107`) uses to
decide whether a scene is mirrored into a local `Display` object. The
remaining nine — `group`, `tab_bar`, `collapsing_header`, `window`, `tree`,
`modal`, `table`, `plot`, `draw` — are absent from that tuple. The mission
framed this as: these nine kinds "bypass Hub authority and handler dispatch."

Reading the code that actually decides Hub authority shows this framing is
wrong for the production path. Two separate stores both bear the name
"Display" in this codebase, and the gap the epic describes lives entirely in
the one that is not authoritative.

### 1.1 `HubDisplay` (luxd) — the real authority — already handles all 25 kinds uniformly, with no kind gate

The production install path for a `show()` call is:

1. `SceneInstaller.install()` (`src/punt_lux/operations/scene_installer.py:49`–`70`)
   runs `SubmissionGate().first_rejection()` first.
2. `SubmissionGate` (`src/punt_lux/domain/submission_gate.py:42`–`53`) runs
   `ElementTreeValidator().validate_tree(roots)` — this walks
   `child_elements()` (`domain/element_abc.py:164`–`188`), which every
   `Element` ABC subclass has, including all nine kinds under investigation.
   There is no kind allow-list here.
3. On a clean tree, `HubDisplay.show_scene()` →
   `HubDisplay.apply(AddElement(...))` (`domain/hub/hub_display.py:285`–`313`)
   calls `SubtreeInstaller.install()`.
4. `SubtreeInstaller.install()` (`domain/hub/subtree_installer.py:65`–`82`)
   recurses via `isinstance(element, Composite)` — a structural Protocol
   check (`domain/composite.py`), not a kind check. Any element exposing a
   `children` tuple recurses; every other element installs as a leaf. Again,
   no kind allow-list.

`tests/domain/test_hub_display_composite_recursion.py` and
`tests/domain/test_subtree_installer.py` already exercise this recursion with
`CollapsingHeaderElement`/`TabBarElement` composites, confirming the claim is
not just a code-reading inference.

**Conclusion:** every one of the nine kinds is already Hub-authoritative,
already self-validating through the same `validate()` walk as `button` and
`checkbox`, and already installed with full parent/child indexing the moment
it is submitted through the real front door. There is no per-kind class-level
work remaining and no HubDisplay-side wiring gap. The 2026-07-27 "25/25 on
the Element-ABC / Hub-Display path" claim is correct for this store.

### 1.2 `domain.display.Display` (the Display-tier mirror) — not authoritative, and its interaction role is already dead

The confusion is that a *second* class, also named `Display`
(`src/punt_lux/domain/display.py`), lives inside the Display-tier process
(`src/punt_lux/display/server.py`, the `lux-display` binary — see
`topology.md`). `DisplayServer` constructs one at startup
(`display/server.py:177`–`183`) and `DomainPump.route()` mirrors every
`_NATIVE_KINDS`-typed scene into it on receipt (`display/server.py:826`–`828`).

This class's own docstring is explicit about what it is:

> "``Display`` (this class) is the **display-process mirror**... Under D21
> the display forwards interactions to the Hub rather than dispatching
> locally, so production interaction dispatch runs on the Hub side;
> ``interact`` here stays the in-process dispatch contract [for tests]."
> (`domain/display.py:7`–`23`)

And `DisplayServer._emit_event`, the real interaction path, confirms the
docstring in code, not just prose:

> "D21: the display no longer dispatches interactions locally via
> ``DomainPump.route_interaction``. The ``remote_dispatch`` handler on each
> element sends the ``RemoteEventHandlerInvocation`` to the Hub, where the
> real handler fires." (`display/server.py:744`–`748`)

Grepping production `src/` (excluding tests) for `.interact(` on this object
returns zero hits — `_domain_display.interact()` is never called outside the
test suite. `DomainPump.route()`'s only live production consumer is
`SceneInspector._mirror_ids()` (`src/punt_lux/scene_inspector.py:76`–`85`),
which feeds one introspection field, and that field's own docstring already
says what it is honestly:

> "``domain_mirror_present`` is an HONEST display-side signal... It is NOT
> Hub authority; the display process cannot read the Hub's ``HubDisplay``."
> (`src/punt_lux/scene_inspection.py:37`–`40`)

### 1.2.1 Confronting `domain/display.py`'s own "It is not vestigial" claim

The class's docstring does not only call itself "the display-process
mirror" (quoted above) — the very next line says, in full: "It is the live
store the display-side dual-write pump writes into: `DisplayServer`
constructs one (`server._domain_display`) and `DomainPump.route` mirrors
every native-kind scene into it. **It is not vestigial.**"
(`domain/display.py:11`–`14`). Citing the rest of that docstring as evidence
while passing over its own explicit self-defense would be asserting past a
direct contradiction, so it is worth being precise about what the claim is
true of and what it is not.

"Not vestigial" is true, and false, depending on which of the two roles
this design distinguishes:

- **As the test-dispatch harness (Q3, kept).** The docstring's very next
  sentence is the load-bearing one: "``interact`` is this class's
  domain-level dispatch surface... used by the test suite to drive the
  handler path in one process." Read in that light, "not vestigial" is
  correct and this design agrees with it — §5 Q3 recommends keeping the
  class for exactly that purpose. A class being a genuine, actively used
  test double is not the same claim as "this class's production wiring in
  `display/server.py` does load-bearing work," and the docstring does not
  actually assert the latter. It says the object is *written into*
  ("mirrors... into it"); it does not say anything is *read from* it, or
  *decided by* it, in production.
- **As production wiring inside `DisplayServer` (Q1/Q2, targeted for
  deletion).** Being written into is not the same as being authoritative,
  and it is not the same as mattering to any decision the running system
  makes. The two pieces of evidence already in §1.2 are about exactly this:
  zero production callers of `.interact()` (nothing acts on what was
  written), and the write's one production reader
  (`domain_mirror_present`) is itself documented as answering a question
  ("is this Hub-authoritative?") that its own docstring says it cannot
  answer. A store that is written to on every scene, read by exactly one
  consumer, and that consumer's own docs disclaim the read as meaningless —
  that is the concrete, evidence-backed sense in which the production
  wiring is dead weight, independent of whatever the class's own docstring
  says about itself. Docstrings describe intent at the time they were
  written; they are not proof of current behavior, and this one is stale
  about the wiring even where it is accurate about the test-harness use.

So the docstring does not undercut Q1/Q2 — it undercuts a version of this
design's claim ("the class is vestigial") that this design does not
actually make. What is recommended for deletion is narrower and stated
precisely in §5: the class's *production wiring* in `display/server.py`,
not the class itself, which the docstring correctly calls not vestigial as
a test fixture.

**Conclusion:** the nine kinds are not missing from `_NATIVE_KINDS` because
of unfinished migration work. They are missing because `_NATIVE_KINDS` and
`DomainPump`'s production wiring of `_domain_display` in `display/server.py`
is itself vestigial — a second authority-shaped write path, left over from
before the Hub/Display process split existed, whose one surviving read
(feeding `domain_mirror_present`) is explicitly documented as not meaningful
for answering "is this element Hub-authoritative." (Per §1.2.1, this claim
is about the wiring, not about the `domain.display.Display` class itself —
the class's separate role as a test-dispatch harness is real and is not what
this conclusion is about.) Widening `_NATIVE_KINDS` to 16→25 would extend
dead architecture, not close a gap. It would also violate `target.md`'s
"Display copies are never authoritative" invariant more broadly than it is
already violated, by giving nine more kinds a locally-`.apply()`-able shadow
copy inside the render process.

This reframes the epic. The defect is not "compose the D21 two-tier model for
nested composites" — that model is already fully proven for every kind, not
just button/dialog (see §2). The defect is that `display/server.py` still
carries this second, non-authoritative, kind-gated write path, which
predates the real Hub/Display split and now does nothing except make the
codebase's real state harder to read — exactly what beads `lux-ttey.2` and
`lux-ttey.3` already anticipated before this design mission ran.

## 2. Per-kind assessment

All nine kinds are **ready — no ABC or Hub-wiring work needed.** Evidence per
kind:

| Kind | ABC subclass | `_children()` override | `validate()` | Interaction routing |
|---|---|---|---|---|
| `group` | `GroupElement` (`protocol/elements/group.py:41`) | yes, plain container (`:97`) | leaf default (no invariant; layout is decoder-checked, `group_codec.py`) | none — display-only |
| `tab_bar` | `TabBarElement` (`tab_bar.py:52`) | yes, `Tab` children (`:122`) | `:186` | tab-select is Display-local view state (documented, not business state) |
| `collapsing_header` | `CollapsingHeaderElement` (`collapsing_header.py:46`) | yes (`:109`) | `:142` | open/closed is Display-local view state |
| `window` | `WindowElement` (`window.py:49`) | yes (`:120`) | `:144` | drag/resize position is Display-local view state |
| `tree` | `TreeElement` (`tree.py:42`) | inherited empty — `nodes` is a typed `TreeNode` value family, not child Elements (documented at `tree.py:9`–`16`, matching ratified Decision (d) for `draw`) | inherited leaf default — node well-formedness is a decode-time (`TreeNode.decode_all`) concern, so nothing invalid survives to be re-checked | none — display-only |
| `modal` | `ModalElement` (`modal.py:85`) | yes (`:176`) | `:207` | **interactive** — `_remote_dispatch_specs()` returns `RemoteDispatchSpec(ModalClosed, self.id, "modal_closed")` (`modal.py:201`–`203`), the same generic seam Button/Checkbox use |
| `table` | `TableElement` (`table.py:52`) | via `resolved_props`/selection model (`table_selection_model.py`) | `:263` | selection routes to the Hub per the ratified authority split (Decision c); filter/search stay Display-local |
| `plot` | `PlotElement` (`plot.py:42`) | leaf, typed `PlotSeries` (`plot_series.py`) | `:132` | none — display-only |
| `draw` | `DrawElement` (`draw.py:40`) | inherited empty — `commands` is a typed `DrawCommand` value family (documented at `draw.py:9`–`16`), not child Elements | inherited leaf default — command well-formedness is a decode-time (`DrawCommandDecoder`) concern | none — display-only |

None of these needs a new ABC method, a new Protocol, or a new decoder. Every
one already satisfies `element-contract.md`'s common contract (stable `id`,
serializes across the boundary, self-validates, fits the two-tier model) and
is exercised by the Hub-side composite recursion tests cited in §1.1. The
"open design question" column that a normal per-kind migration table would
carry is empty for all nine — the open questions in this design (§5) are all
about the *Display-tier mirror*, not about any element kind.

## 3. The wiring mechanism for nested composites (already built, already proven beyond button/dialog)

This was the mission's second required item — "how a tree of elements is
installed, self-validates, replicates, and re-dispatches child interactions."
It does not need to be designed; it needs to be described, because it is
already load-bearing production code and the epic's framing implied it only
covered the button/dialog pair.

1. **Self-validation, whole-tree, before install.** `ElementTreeValidator`
   walks every element's `child_elements()` and accumulates every
   `ValidationError` across the hierarchy — no fail-fast, per
   `element-contract.md` §Validation Contract. A tree with one invalid
   `Tab` nested three `group`/`collapsing_header` levels deep is rejected
   whole; nothing partial installs. This is generic over kind — it dispatches
   on the `child_elements()` Protocol method, never on `isinstance` of a
   concrete class.
2. **Install, whole-tree, into `HubDisplay`.** `SubtreeInstaller.install()`
   recurses on the `Composite` Protocol (`domain/composite.py`) — any element
   with a `children` property. It records each node in `ElementIndex`,
   `OwnerTracker`, and (for the root) `RootRegistry`, and records
   parent→child edges in `ChildIndex` so cascade removal works at any depth.
   A `window` containing a `group` containing a `collapsing_header`
   containing a `tab_bar` containing `Tab`s containing `button`s installs in
   one call, each node keyed by `(scene_id, element_id)`.
3. **Replication to the Display.** `HubReplicator` (see
   `mcp-display-liveness.md`) resends the whole scene on a dirty mark — the
   default whole-tree-resend policy `target.md` specifies. This is
   kind-agnostic; it operates on the serialized scene, not per-element.
4. **Handler wrapping, whole-tree, on receipt.** `DisplayServer._wrap_abc_elements`
   (`display/server.py:816`–`824`) calls `elem.wrap_handlers_for_remote(self._emit_event)`
   on every top-level element in the incoming `SceneMessage`.
   `wrap_handlers_for_remote` (`domain/event_handler_host.py:122`–`147`)
   recurses `_children()` and, for each element, iterates
   `_remote_dispatch_specs()` — the declarative seam every interactive kind
   implements (Button's `ButtonClicked`, Checkbox's `ValueChanged`, Modal's
   `ModalClosed`). This already resolved the audit's Decision (e) ("the
   wrap-seam must not hard-code isinstance branches") — it is not an open
   question for this design, it is a shipped generalization. A `button`
   nested inside a `tab_bar` inside a `window` gets wrapped by the same
   recursive call that wraps a top-level button; depth is not special-cased
   anywhere in this path.
5. **Re-dispatch on interaction.** A click fires the wrapped handler, which
   sends one `RemoteEventHandlerInvocation` to the Hub via `_emit_event`. The
   Hub resolves the element by `(scene_id, element_id)` in `ElementIndex` —
   depth-independent, since the index is flat and keyed by id, not by tree
   position — and fires the real handler
   (`domain/hub/hub_interaction_dispatch.py`).

Every step above is generic over "any `Element` ABC subclass," proven today
by `group`/`tab_bar`/`collapsing_header`/`modal`'s own tests plus the
button/dialog exemplar. There is no design gap here to close; the mission's
premise that this needed proving for "a nested tree, not just a leaf" is
already settled by the cited tests.

## 4. `draw` categorization — resolved: leaf, not composite

`draw` was named in the mission as needing an explicit resolution because it
is display-only but structurally rich (a canvas of typed drawing commands).
It is a **leaf, not a composite**, and this was already decided and
implemented correctly, matching the audit's ratified Decision (d):

- `DrawElement._children()` is the inherited empty default —
  `commands: tuple[DrawCommand, ...]` is a typed value family
  (`draw_commands_curve.py`, `_line`, `_shape`, `_text`), not a tuple of
  child `Element`s. Draw commands have no `id`, no handler registry, and no
  independent render call — `element-contract.md`'s "What Elements Must Not
  Become" explicitly warns against giving line segments ids and handler
  registries.
- `DrawElement`'s own module docstring states this reasoning directly
  (`draw.py:3`–`16`): commands are "a typed `DrawCommand` value family (no
  more `list[dict]`), not child elements," and command well-formedness is a
  decode-time concern (`DrawCommandDecoder`), so `validate()` correctly
  inherits the leaf default rather than re-walking an already-validated
  value family.
- `tree`'s `nodes: tuple[TreeNode, ...]` is the identical shape and follows
  the identical reasoning, cited in `tree.py`'s own docstring as copying
  `draw`'s precedent.

`draw` therefore belongs in this epic's scope only as "confirm it needs
nothing" — which §2's table already shows — not as composite-wiring work.

## 5. Open questions — ratified by the operator

These were the design forks this investigation surfaced. Nothing in §§1–4
was a fork — they are corrections of the epic's stated premise, backed by
reading the shipped code and its own docstrings, which already state the
conclusions above. The forks were about what to do with the vestigial
Display-tier mirror *wiring* (per §1.2.1: the production write path, not the
`domain.display.Display` class itself) and, for Q3, the class itself. All
three are now ratified; each entry below states the original recommendation,
the ruling, and the reasoning.

**Q1 — RATIFIED as recommended: delete `DomainPump`, `_NATIVE_KINDS`, and
`_domain_display`'s production wiring from `display/server.py` outright.**

The wiring's interaction role is already dead (D21, §1.2), its install role
duplicates work `HubDisplay` already does authoritatively one process over,
and its one live consumer (`domain_mirror_present`) is a field the code's
own docstring says answers the wrong question ("NOT Hub authority").
Keeping it would have meant every future element kind must remember to
appear in *two* places (`_NATIVE_KINDS` and nowhere else, since Hub install
needs no per-kind list) for no behavioral gain — exactly the kind of
asymmetry this epic exists to close. This is bead `lux-ttey.2`'s scope; this
design confirmed and grounded it rather than proposing something new.

**Q2 — RATIFIED as recommended: retire both `domain_mirror_present` and
`render_path` from the `inspect_scene` wire schema, in the same change that
deletes the mirror.**

`SceneInspection`/`ElementInspection` (`src/punt_lux/scene_inspection.py`)
lose their one variable field once Q1 lands — `render_path` was already a
constant `Literal["abc"]` per its own comment
(`scene_inspection.py:27`–`29`, "kept... no reader breaks"), which was
itself a small back-compat shim the org's no-shim rule would ordinarily
forbid. A constant field and a field that answers a question nobody should
be asking are both debt, not a stable contract worth preserving
byte-for-byte. If Hub-authority introspection is wanted later, it must be
added to a query the Hub itself answers (luxd has `HubDisplay`; the Display
process does not and structurally cannot per target.md's tier separation),
which is new scope beyond this epic, not a reason to keep the current
dishonest-by-omission field around in the meantime.

**Q3 — RATIFIED (operator, superseding this design's original
recommendation): delete `domain.display.Display` entirely; retarget its test
callers to construct and drive `HubDisplay` directly.**

This design originally recommended keeping the class as a test-only
in-process dispatch harness, on the reasoning that it predated `HubDisplay`
and gave the test suite an in-process double for D21 dispatch mechanics
without `HubDisplay`'s locking and session machinery. The operator's ruling
rejects that reasoning on a fact this design had not checked:
`HubDisplay.__new__` (`domain/hub/hub_display.py:106`) takes only an
optional clock callable — no socket, no session, no luxd dependency — so it
is exactly as constructible in a single test process as `Display` is. The
justification for a separate class is gone. Keeping it means every future
change to ownership, dismissed-ancestor, or click-validation logic has to be
made correctly in two independently maintained implementations — `Display`'s
hand-rolled dicts versus `HubDisplay`'s `ElementIndex`/`OwnerTracker`/
`RootRegistry`/`ChildIndex` — or they drift, and `Display`'s 885-line test
file (`tests/domain/test_display.py`) stops proving anything about what
actually ships. This design accepts the correction; §6's sequencing below
is revised accordingly.

**In-process callability of the real Hub dispatch path — verified, already
established.** The operator's ruling depends on whether `HubDisplay`'s real
click-dispatch path is callable in a test process without a live connection
or socket, or needs new production code first. It is already callable, with
no new production code needed, and the pattern is not hypothetical — it is
already shipped and in use:

- `HubInteractionDispatch.dispatch()` (`domain/hub/hub_interaction_dispatch.py:29`–`46`)
  is a `@staticmethod` that resolves the element via a module-level
  singleton `hub_display: HubDisplay` (constructed once at import,
  `hub_display.py:344`) and marks the scene dirty via a second module-level
  singleton, `hub_replicator` (`replicator_instance.py`). Neither is passed
  as a parameter — the dispatch closes over the process-wide instances.
- `tests/domain/test_hub_interaction_dispatch.py` already exercises this in
  process against a *test-local* `HubDisplay()` — not the process-wide
  singleton — by constructing `isolated_display = HubDisplay()`, populating
  it with `isolated_display.apply(AddElement(...))`, and then using
  `monkeypatch.setattr(hub_module, "hub_display", isolated_display)` plus
  `monkeypatch.setattr("...replicator_instance.hub_replicator", MagicMock())`
  before calling `HubInteractionDispatch.dispatch(...)`. The test then
  asserts the real, unstubbed handler chain ran
  (`test_hub_interaction_dispatch_runs_grouped_button_handlers_once`,
  `tests/domain/test_hub_interaction_dispatch.py:26`–`70`).

So the answer to "already callable, or needs a new in-process entry point"
is **already callable — retarget imports and follow the established
monkeypatch-the-two-singletons pattern.** No new production code is needed
on `HubDisplay` or `HubInteractionDispatch` to make this migration clean;
the seam this ruling depends on already exists and already has a working
example to copy, not just a theoretical path.

## 6. Migration sequencing plan

Because §1 corrects the epic's premise, the sequencing is corrective and
small, not additive — with one exception, noted below, now that Q3 is
ratified as a full deletion rather than this design's original
keep-as-fixture recommendation. No PR needs "wire kind X into native
kinds" — that work does not exist. The sequence below reflects the
operator's ratified Q1/Q2/Q3, and each PR is independently revertible.

**PR 1 — Correct the false completeness claims (bead `lux-ttey.5`).**
Fix the "legacy path deleted, 25/25 migrated" framing in
`docs/architecture/element-migration-audit.md` and
`docs/architecture/migration/README.md` to state precisely what §1 of this
document establishes: the class-level migration is genuinely complete and
Hub-authoritative for all 25 kinds; the claim that needs qualifying is only
about the Display-tier's separate, non-authoritative `DomainPump` mirror,
which this epic's later PRs remove. Docs-only; no code risk; can land
independently and immediately — no dependency on the rest of this sequence,
since it only removes a false claim rather than asserting a new one.

**PR 2 — Delete `DomainPump`, `_NATIVE_KINDS`, `_domain_display` production
wiring, and `SceneInspector`'s `domain_mirror_present`/`render_path` fields
(bead `lux-ttey.2`).**
Remove `display/domain_pump.py`'s use from `display/server.py`
(`_domain_pump`, `_domain_client_id`, `_route_to_domain_display`,
`_BASICS_KINDS`/`_INPUTS_KINDS`/`_COMPOSITE_KINDS`/`_NATIVE_KINDS`). Delete
`display/domain_pump.py` itself and `tests/test_domain_pump.py` wholesale —
that file tests `DomainPump` mechanics directly (wire-shape triage, native-kind
routing), not general `Display` behavior, so it has no retargetable content;
it is removed, not migrated. This PR also retires `domain_mirror_present`
and `render_path` from `scene_inspection.py`/`scene_inspector.py` per Q2 —
scoped here rather than as a separate PR because both changes are causally
tied to deleting the mirror that fed them, and doing them together avoids an
intermediate commit where `SceneInspector` still reports a field with no
backing mirror.

**PR 3 — Delete `domain.display.Display` and retarget its remaining test
callers to `HubDisplay` (bead `lux-ttey.2`, split from PR 2 — see rationale
below).**
Delete `src/punt_lux/domain/display.py`. Retarget the seven test files still
importing it — `tests/domain/test_display.py` (885 lines),
`tests/test_scene_inspector.py`, `tests/integration/test_disconnect_lifecycle.py`,
`tests/regression/test_dialog_interaction_trace.py`,
`tests/test_inputs_migration.py`, `tests/test_abc_wire_roundtrip.py`,
`tests/domain/test_basics_migration.py` (2629 lines combined) — to construct
`HubDisplay()` directly and drive dispatch through
`HubInteractionDispatch.dispatch()`, following the
`monkeypatch.setattr(hub_module, "hub_display", ...)` /
`monkeypatch.setattr("...replicator_instance.hub_replicator", MagicMock())`
pattern `tests/domain/test_hub_interaction_dispatch.py` already establishes
(§5 Q3). `tests/domain/test_display.py` itself is the largest single file
and is a straight port of its assertions onto the `HubDisplay` API surface —
`ElementIndex`/`OwnerTracker`/`RootRegistry`/`ChildIndex` replace `Display`'s
hand-rolled dicts, so each assertion has a direct new home, not a redesign,
**with one known exception**: `test_display.py`'s `UnauthorizedInteractionError`
and `ElementDismissedError` assertions (raised by `Display.interact()`) have
no direct equivalent on `HubInteractionDispatch`'s real production dispatch
path today, a separately tracked and independently owned gap. PR 3's port
should either drop those two specific assertions with that stated reason, or
carry them forward as an explicitly noted coverage gap rather than silently
losing them — whichever the implementer judges cleaner — but should not
invent a new production authorization check as part of this epic's scope to
paper over it.

**Why PR 3 is split from PR 2, not folded in:** PR 2 is a deletion of dead
production wiring with a small, mechanical test footprint (delete one test
file). PR 3 is ~2,600+ lines of test retargeting across seven files, each
requiring a working understanding of `HubDisplay`'s real API to port
correctly rather than a mechanical find-replace — a materially different
review shape and risk profile. Splitting keeps PR 2 fast to review and merge
(it is the change §1 already fully justifies) without making it wait on the
larger, slower-to-review test port, and keeps a regression introduced in the
test port isolated to a revert of PR 3 alone, not also reverting the
production deletion PR 2 already landed. This is the one place this
design's sequencing is no longer "small" — flagged explicitly rather than
understated, per the operator's ratification changing Q3's scope.

**PR 4 — Extend `test_no_legacy_path.py` (bead `lux-ttey.4`).**
Add `DomainPump`, `_NATIVE_KINDS`, `domain.display.Display`, and
`domain_mirror_present` to the forbidden-pattern / deleted-module guard so
this specific vestigial-wiring category of defect cannot silently reappear,
the same structural guarantee the test already gives the `Legacy*` dataclass
family. This PR depends on PR 2 *and* PR 3 landing first (the guard would
otherwise fail against code it is meant to protect going forward).

**PR 5 — `SceneManager`'s role: justify, not retire (bead `lux-ttey.3`).**
`SceneManager` is not a hidden second authority — it is the Display's
`target.md`-sanctioned rendering/input-capture replica (frame and tab
bookkeeping, `WidgetState`, and `elem.render()` iteration at
`display/server.py:1086`–`1089`, which already paints every kind uniformly
regardless of `_NATIVE_KINDS`). No deletion work exists here; this PR is a
documentation-only pass adding a short "why this class exists and does not
duplicate HubDisplay" note to `scene/manager.py`'s module docstring, closing
the bead by clarifying rather than by code change.

**PR 6 — Clean stale `__pycache__` artifacts (bead `lux-ttey.6`).**
Mechanical, no design content; sequence last or in parallel — it has no
dependency on PRs 1–5 and no dependency from them.

Each PR above is a self-contained, rollback-coherent unit per `WORKFLOW.md`'s
PR-loop sizing guidance. PR 3 must follow PR 2 (it deletes the class PR 2's
production code stops depending on); PR 4 must follow both PR 2 and PR 3;
PR 1 and PR 6 have no ordering constraint with the others.
