# ABC-Baseline Debt Audit

**Status:** audit only — no code changed. Adversarial trace of the
Element-ABC / Hub-Display exemplar foundation (the four migrated kinds:
`text`, `button`, `checkbox`, `dialog`).

**Method:** actual behaviour traced through the code. No docstring or comment
was trusted; every claim was checked against the source and against
`grep`-verified call graphs. Findings below cite `file:line` for both the
defect and the evidence.

**Relationship to the render-path work:** the paint-path fragmentation (the
`isinstance(TextElement)` special-case in `_paint_element`, the duplicated
paint branch in `_render_scene_tab`, the `Renderer` Protocol docstring
rewrite, the `element_kind_count` coupling, the `ImGuiTextRenderer`
delegation) is owned by
[render-path-unification-design.md](./render-path-unification-design.md).
Those items are referenced here where a finding touches them, but they are
**not** re-listed as new debt. This audit covers debt **outside** that design.

## Headline

The foundation's central story — "each Element carries a `RendererFactory`
injected at decode time, and the display tier injects its real ImGui factory
so `Element.render()` paints" — **is not true anywhere in the running code.**
Every ABC element in every tier carries the fail-loud `RAISING_FACTORY`
sentinel. The real `ImGuiRendererFactory` is never bound onto any element; it
is only ever invoked at the paint **call site**
(`server.py:1465`, `server.py:1510`). The template method `Element.render()`
has **zero production callers**. Production does not crash today only because
the paint path sidesteps `elem.render()` entirely.

Three module docstrings assert the opposite of this (`factory.py`,
`raising.py`, `renderer.py`), and the render-path-unification design repeats
the false premise (`§6`, citing `factory.py:3-6`). When that design flips
`_paint_element` to call `elem.render()`, the sentinel factory fires and the
first frame raises `RuntimeError`. The rebind that would make the flip safe
**does not exist** and is outside the design's stated change set. That is the
top blocking item.

## Severity summary

| ID | Sev | Cat | One-line |
|----|-----|-----|----------|
| C1 | BLOCKING | wiring | Real ImGui factory never rebound onto pickled/decoded elements; `elem.render()` would hit `RAISING_FACTORY` |
| A1 | BLOCKING | doc-lie | `factory.py` claims decode-time threading of the ImGui factory; never happens |
| A2 | BLOCKING | doc-lie | `raising.py` claims the display sidesteps at decode time; the sidestep is at the paint call site |
| I1 | BLOCKING | test | `Element.render()` covered only via a non-production `RecordingRendererFactory` (monkeypatched premise) |
| A3 | MODERATE | doc-lie | `element_abc.py` / `renderer.py` call the template method "never overridden" and describe a live path that is dead |
| A4 | MODERATE | doc-lie | element + codec docstrings claim decode "passes real values"; the real value is always the sentinel |
| A5 | MODERATE | doc-lie | `ImGuiTextRenderer` docstring's stated reason ("`Element.render()` calls it polymorphically") is fictional today |
| C2 | MODERATE | wiring | `_wrap_abc_elements` is the natural rebind site but rebinds nothing |
| C3 | MODERATE | OPEN | ABC element nested in a legacy dataclass container is not rebound or handler-wrapped — would hit `RAISING_FACTORY` under the PR2 `render()` flip; resolved by the migration strategy, not a legacy-container walk |
| D1 | MODERATE | oo | `messages/scene.py` codec is fully procedural; `str`-with-comment + raw-dict boundary |
| D2 | MODERATE | coupling | `scene.py` imports `_element_to_dict` / `_strip_none` — cross-package private reach-around |
| E4 | MODERATE | special-case | `Display._build_event` branches on `element.kind == "button"/"checkbox"` strings |
| F2 | MODERATE | coupling | `render_element` probes `getattr(elem, "style"/"tooltip")` — soft `hasattr` (PY-TS-10) |
| G1 | MODERATE | dead | `ImGuiRendererFactory` holds `widget_state`/`texture_cache`/`emit` that no renderer reads |
| I2 | MODERATE | test | Negative `render()`-raises test passes only because the positive path is dead |
| A7 | MINOR | doc-lie | Tombstone + meta-reference comments; "installed by the display-side factory" is wrong |
| A6 | MINOR | doc-lie | `RendererFactory` Protocol docstring repeats the decode-time-threading claim |
| E2 | MINOR | special-case | `element_factory` enumerates the four ABC kinds where an ABC check belongs |
| E3 | MINOR | special-case | `domain_pump._ABC_TYPES` enumerates the four kinds where an ABC check belongs |
| D3 | MINOR | oo | `element_from_dict` returns `Any`, takes `dict[str, Any]` at the top decode boundary |
| D4 | MINOR | oo | `SceneInspector.inspect` swallows `**_kwargs: Any` |
| F3 | MINOR | coupling | Display replica mutates its own `model.close()` (Display-side authority write) |
| G3 | MINOR | dead | `ImGuiRendererFactory.__call__` docstring carries a stale "Button/Panel/…" plan |
| H2 | MINOR | dup | `canonicalize_button_sugar` re-invoked via a lazy import to dodge a cycle |

## (a) Docstring / comment vs reality

The hardest-hunted category — the render-path review proved these hide crash
bugs. Each claim below was checked against the call graph.

### A1 — BLOCKING — `ImGuiRendererFactory` claims decode-time threading

`factory.py:1-11` (module docstring) and `factory.py:78-82` (`__call__`
docstring) state the factory is "threaded through every element constructed
during decode" and that "per-kind renderers receive the factory."

**Reality:** no element ever receives an `ImGuiRendererFactory`. The two
`JsonElementFactory` construction sites both pass `RaisingRendererFactory()`
(`server.py:233`, `hub_factory.py:78`). The `ImGuiRendererFactory` is
constructed at `server.py:260` and invoked **only** at the paint call sites
`server.py:1465` and `server.py:1510` as `self._imgui_renderer_factory(elem).render()`.
`grep` for callers of `elem.render()` in `src/` returns none.

**Why it is debt:** the docstring describes the intended architecture as if it
were implemented. A reader copying this exemplar for a new kind will wire DI
that is never exercised and will not discover the gap until the paint flip
crashes. This doc is load-bearing misinformation.

**Fix:** rewrite the docstring to state the truth — the factory is a
paint-call-site resolver, not an element-borne dependency — and, jointly with
C1, make the decode-time claim true by rebinding the factory on the Display.

### A2 — BLOCKING — `RaisingRendererFactory` describes a sidestep that does not exist

`raising.py:11-13`: "The display tier sidesteps this factory at decode time by
injecting its own `_imgui_renderer_factory`."

**Reality:** false on two counts. (1) The display tier's own
`JsonElementFactory` is constructed with `RaisingRendererFactory()`
(`server.py:233`) — it does not inject an ImGui factory at decode. (2) On the
Display, ABC elements do not arrive by decode at all: they arrive as pickled
`_pickled` entries (`scene.py:82-83` encode, `scene.py:121-128` decode), and
`Element.__reduce__` (`element_abc.py:79-93`) preserves `_renderer_factory` —
i.e., the Hub's `RAISING_FACTORY` — verbatim. The real sidestep is at the
paint call site (`server.py:1465`), exactly as the task described.

**Why it is debt:** this is the specific lie that hid a first-frame crash. It
tells a maintainer the DI is sound when the guard it documents has never once
fired in production.

**Fix:** rewrite to describe the sentinel's actual role (a Hub/Agent-tier
guard that fires only if someone calls `elem.render()` off the display tier),
and land the C1 rebind so the guard's promise ("inject a display-tier factory
at decode time") is real.

### A3 — MODERATE — template-method docstrings describe a dead live path

`element_abc.py:5` and `:106-107` call `render()` a "template method per
Composite pattern; NEVER overridden," and `renderer.py:22-25` says "The
Element ABC's template method chooses which path to take based on whether
`_children()` is empty."

**Reality:** `Element.render()` (`element_abc.py:106-118`) has zero production
callers (see A1). The `renderer.py:22-25` rewrite is owned by the render-path
design `§4`; the deeper fact — that the method is dead **today**, not merely
mis-described — is not stated there.

**Fix:** the render-path PR revives the method; until then the docstring must
not present a dead path as the live rendering algorithm. Reference the design;
add a one-line "not yet on the production paint path" note.

### A4 — MODERATE — element and codec docstrings claim decode "passes real values"

`text.py:6-7`, `button.py:6-8`, `checkbox.py:6-8`, `abc_di_defaults.py:5-8`,
and `text_codec.py:8-10` all state that the wire decode path "always passes
real values, so the runtime DI shape on the wire path is unchanged" / "the
element is born with its DI wired in."

**Reality:** the value passed for `renderer_factory` is *always*
`RaisingRendererFactory` (`server.py:233`, `hub_factory.py:78`,
`text.py:141`, `button.py:175`, `checkbox.py:135`, `dialog.py:254`). "Real
value" is technically the tier's factory, but the implied meaning — a
display-capable factory reaches the element — is false for every tier.

**Fix:** state that the display-capable factory is bound by the Display's
post-decode rebind (C1), not by the decoder.

### A5 — MODERATE — `ImGuiTextRenderer` docstring's stated purpose is fictional

`text.py:1-13` (renderer module) says the adapter exists "so the
template-method `Element.render()` can call it polymorphically," and
`text.py:48,51` say the no-op `begin`/`end` exist because "`Element.render()`
never calls this."

**Reality:** `Element.render()` never calls `ImGuiTextRenderer` at all in
production; `_paint_element` calls `ImGuiTextRenderer.render()` **directly**
through the factory (`server.py:1465`). The stated raison d'être is aspirational.

**Fix:** covered by the render-path design once the flip lands; until then the
docstring should not assert a call that does not happen.

### A6 — MINOR — `RendererFactory` Protocol docstring repeats the false claim

`renderer.py:36-38`: "One factory per Display, constructed once at startup and
threaded through the element tree at decode time." Same falsehood as A1.

**Fix:** fold into the A1 rewrite.

### A7 — MINOR — tombstone, meta-reference, and a wrong attribution

- `domain_pump.py:167-169` — comment "route_interaction removed by D21: …" is
  a tombstone (PL-PP-1: no `# removed` comments) and a meta-reference (`D21`
  belongs in git history, not source). Delete it.
- `button_renderer.py:27-30` and `checkbox_renderer.py:22-27` — "handlers are
  wrapped by `remote_dispatch` (installed by the display-side factory)."
  **Wrong attribution:** the wrapping is installed by
  `DisplayServer._wrap_abc_elements` (`server.py:933-945`) calling
  `elem.wrap_handlers_for_remote(...)`, not by any factory. A reader chasing
  "the display-side factory" for the wrapping will not find it.

**Fix:** delete the tombstone; correct the attribution to `_wrap_abc_elements`.

## (c) Missing / broken wiring — DI gaps

### C1 — BLOCKING — the display factory is never rebound onto received elements

**Trace:** Hub decodes agent JSON via `hub_element_factory`
(`hub_factory.py:77-82`) with `RaisingRendererFactory` → ABC elements carry
`RAISING_FACTORY`. Hub pickles them into the scene message
(`scene.py:79-84`). `Element.__reduce__` keeps `_renderer_factory` in state
(`element_abc.py:92`). Display unpickles (`scene.py:126-128`); `__setstate__`
(`element_abc.py:95-99`) restores every field except `_observers` — so the
Display element still carries `RAISING_FACTORY`. Nothing rebinds it:
`_wrap_abc_elements` (`server.py:933-945`) wraps handlers but not the factory,
and `_paint_element` (`server.py:1462-1467`) resolves a renderer at the call
site instead of via the element.

**Why it is BLOCKING:** the render-path-unification design `§6` flips
`_paint_element` to `if isinstance(elem, ElementABC): elem.render()`. That
calls `self._renderer_factory(self)` (`element_abc.py:108`) →
`RaisingRendererFactory.__call__` → `RuntimeError` (`raising.py:38-45`) → the
first frame that paints an ABC element crashes. The design asserts the factory
"threads through every element at decode time (factory.py:3-6)" and defers to
"the worker must confirm this wiring holds" — but the premise it cites is A1,
which is false. The rebind is **not** in the design's change set.

**Fix:** on the Display, after `pickle.loads`, walk each received ABC element
tree and rebind `_renderer_factory` to the Display's `ImGuiRendererFactory`
(the natural home is `_wrap_abc_elements`, which already iterates the ABC
elements post-receive — see C2). Add a boundary test: a received element
carries `RAISING_FACTORY` before rebind and the ImGui factory after
(this also closes I1). Land this **before** the render-path flip.

### C2 — MODERATE — `_wrap_abc_elements` is the rebind site but rebinds nothing

`server.py:933-945` already walks every top-level element, checks
`isinstance(elem, AbcElement)`, and mutates it (handler wrapping). It is the
single post-receive ABC hook and the correct place to also set the renderer
factory. Today it does only half the job.

**Fix:** extend it (or a sibling walk it calls) to rebind the factory
recursively through `_children()`, so composites (dialog buttons) are rebound
too. Implements C1.

### C3 — MODERATE — OPEN — ABC element nested in a legacy container is not rebound or wrapped

**Scope decision (deliberate, not a defect to fix here).** The C1/C2 rebind in
`DisplayServer._wrap_abc_elements` (`server.py`) covers ABC elements and their
ABC `_children()` subtrees only — a dialog and its buttons. An ABC element
nested inside a **legacy dataclass container** (`GroupElement`, `WindowElement`,
`TabBarElement`, `CollapsingHeaderElement`, `ModalElement` — none subclass
`Element`) is **not reached**: the top-level pass sees the container (a non-ABC
dataclass), does not descend into its `children`, and the nested ABC element
keeps the Hub-tier `RAISING_FACTORY` and its unwrapped handlers.

**Two consequences:**

1. **Factory not rebound.** The nested ABC element still carries the fail-loud
   sentinel. It renders fine today (paint sidesteps `elem.render()` — see A1),
   but the moment the render-path PR flips `_paint_element` to call
   `elem.render()`, painting that element raises `RuntimeError`
   (`raising.py:38-45`).
2. **Handlers not wrapped — and already dropped.** Even the wrap is moot: a
   legacy container serializes its `children` via
   `container_dispatch.dispatch.to_dict` = `_element_to_dict`
   (`elements/__init__.py:183-193`), which JSON-encodes an ABC child through
   `JsonButtonEncoder` / `JsonCheckboxEncoder`. Those emit only declarative
   fields, not the live `_handlers` closures, so the Hub-side handlers
   (`call_model`, `publish`) are lost on the JSON leg regardless of any wrap.
   (Top-level ABC elements avoid this: they cross as a `_pickled` blob,
   `scene.py:82-83`, and `Element.__reduce__` preserves `_handlers`.)

**Why it is not fixed in this PR.** A legacy-container tree-walk (descend through
`child_elements` to rebind/wrap nested ABC elements) plus preserving handler
closures across the JSON leg is **coexistence machinery** — it only matters
while ABC and legacy element kinds are mixed in one composite. The migration may
compress that window (family-batch / big-bang), migrating the container kinds
onto the Element ABC so their whole subtree crosses as `_pickled`; then this gap
closes with no dedicated walk. Building the walk now risks writing code the
strategy discards.

**Status:** OPEN — the mid-migration rule is: **do not nest an ABC element inside
a legacy dataclass container.** Resolution is a migration-strategy decision
(compress the mixed window / migrate the containers), not a legacy-container walk
here. The seam carries a one-line comment in `DisplayServer._wrap_abc_elements`
noting the ABC-subtree-only coverage.

## (b) Fragmentation / half-migrations

The paint-path split — `text` on the factory path, `button`/`checkbox`/`dialog`
on the legacy `ElementRenderer` path — is the core subject of
[render-path-unification-design.md](./render-path-unification-design.md)
(`§1`, `§2`, `§6`). It is **not** re-listed here. The DI-rebind gap (C1) is the
piece of that fragmentation the design does not cover.

## (e) Special-cases that should be general

### E4 — MODERATE — `Display._build_event` branches on kind strings

`domain/display.py:330-379` selects the event type with
`if element.kind == "button"` / `if element.kind == "checkbox"`. Adding a new
interactive kind means editing this string ladder. A typed per-kind event
factory (isinstance against the element type, or an event map keyed by type)
generalizes it and keeps the "future kinds add their own typed events" comment
honest.

**Fix:** dispatch on element type via a small registry the kinds contribute to.

### E2 — MINOR — `element_factory` enumerates the four ABC kinds

`element_factory.py:184-186` and `:200-202` guard with
`isinstance(abc_elem, TextElement | ButtonElement | CheckboxElement | DialogElement)`.
`AbcElement` is already imported (`element_factory.py:22`). The enumeration
must be edited every time a kind migrates.

**Fix:** `isinstance(abc_elem, AbcElement)`.

### E3 — MINOR — `domain_pump._ABC_TYPES` enumerates the four kinds

`domain_pump.py:33-38` builds `_ABC_TYPES` from the four element classes and
`_with_unique_id` checks `isinstance(elem, _ABC_TYPES)` (`:134`). Same
maintenance hazard; `ElementABC` is the general predicate.

**Fix:** import the ABC and check against it.

## (f) Coupling / encapsulation leaks

### F2 — MODERATE — `render_element` probes attributes with `getattr`

`element_renderer.py:224-231` uses `getattr(elem, "style", None)` and
`getattr(elem, "tooltip", None)` to decide tooltip handling across kinds —
a soft `hasattr` that PY-TS-10 bans. The render-path design `§2` extracts this
block into `apply_tooltip` **verbatim, including the guard**, so the smell
survives that change; it is therefore debt outside the design.

**Fix:** define a `Tooltipped` (and, if needed, `Styled`) Protocol and narrow
with `isinstance`, so the tooltip surface is typed rather than duck-probed.

### F3 — MINOR — Display replica mutates its own dialog model

`dialog.py (imgui):105-106` — `_handle_external_close` calls
`self._elem.model.close()`, a **Display-side** authority write, whereas D21
routes interactions to the Hub. The render-path design `§5` preserves this
deliberately; flag for confirmation that a Display-local dismiss write is
intended rather than routed.

## (g) Dead code / vestigial hooks

### G1 — MODERATE — `ImGuiRendererFactory` carries state no renderer reads

`factory.py:32-34` stores `_widget_state`, `_texture_cache`, `_emit` and
exposes them via three properties (`:52-65`). `grep` across
`display/renderers/imgui/` shows the only accessor any renderer reads is
`element_renderer` (`text.py:45`). `server.py:260-268` constructs the factory
passing `widget_state`, `texture_cache`, and an `emit` lambda — all three are
dead. The render-path design's D4 has future renderers read `element_renderer`
too, so these stay dead post-design.

**Fix:** drop the three fields, their properties, and the constructor
arguments; keep only `element_renderer`.

### G3 — MINOR — stale plan in `__call__` docstring

`factory.py:82-86` — "Text only for now; Button/Panel/Dialog/Window/… cases
are added as their families gain dedicated renderer adapters." A plan-in-a-
comment; the render-path design supersedes it.

**Fix:** remove once the design's factory dispatch lands.

## (h) Duplication

The two `_paint_element` call sites (`server.py:1462-1467` and the inlined
branch at `server.py:1508-1512`) are collapsed by the render-path design `§6`
— **not** re-listed here.

### H2 — MINOR — `canonicalize_button_sugar` re-invoked via lazy import

`dialog_codec.py:118-125` calls
`JsonElementFactory.canonicalize_button_sugar` through a function-body import
to dodge a circular import. Acceptable delegation, but the lazy import signals
the sugar-canonicalization helper wants to live in a shared low-level module
both factories import at top level.

**Fix:** move `canonicalize_button_sugar` to a leaf module (e.g. next to the
button codec) and import it normally from both sites.

## (d) Procedural / OO debt

### D1 — MODERATE — `messages/scene.py` codec is fully procedural

`scene.py` defines the frozen dataclasses `SceneMessage` / `UpdateMessage` /
`ClearMessage` and then a pile of module-level functions that read and build
them: `_scene_to_dict` (`:73`), `_update_to_dict` (`:102`), `_clear_to_dict`
(`:110`), `_scene_from_dict` (`:114`), `_parse_frame_size` (`:60`),
`register_codecs` (`:169`). Per PY-OO-5 / PY-OO-7 these are missing methods —
the four migrated elements already moved codecs into `Json*Encoder` /
`Json*Decoder` classes; the scene message codec did not. Two more smells in the
same file:

- `SceneMessage.layout: str = "single"  # "single", "rows", "columns", "grid"`
  (`scene.py:36`) — `str`-with-comment; the comment is the type system giving
  up (rule #4). Use `Literal["single", "rows", "columns", "grid"]`.
- `frame_flags: dict[str, bool] | None` (`scene.py:40`) — raw-dict boundary
  without a justification (PY-TS-14).

**Fix:** extract `SceneMessageCodec` / `UpdateMessageCodec` classes (or
`to_dict`/`from_dict` methods), replace the `layout` `str` with a `Literal`,
and model `frame_flags` as a typed value.

### D2 — MODERATE — `scene.py` reaches into cross-package privates

`scene.py:11-17` imports `_element_to_dict` and `_strip_none` — leading-
underscore module privates from `protocol.elements` — across the package
boundary. The public `element_to_dict` already exists (used at
`scene_inspection.py:22`).

**Fix:** import the public surface; keep the underscore helpers private to
their module.

### D3 — MINOR — `element_from_dict` is `Any`-in / `Any`-out

`element_factory.py:169` — `element_from_dict(self, d: dict[str, Any]) -> Any`.
This is the most-used decode entry point, and it defeats typing at both ends
while the private `decode` (`:116`) is precisely typed (`-> AbcElement`).

**Fix:** type the return as the `Element` protocol; type the parameter as
`Mapping[str, object]` (the wire boundary), narrowing internally.

### D4 — MINOR — `SceneInspector.inspect` swallows untyped kwargs

`scene_inspector.py:36` — `inspect(self, scene_id: str = "", **_kwargs: Any)`.
A registered query handler that silently accepts any keyword hides
dispatcher/handler signature drift.

**Fix:** give the dispatcher a typed handler signature and drop `**_kwargs`, or
document the exact kwargs it must tolerate.

## (i) Test-coverage debt

### I1 — BLOCKING — the template method is covered only by a fake factory

`Element.render()` is exercised by `test_text_recording.py:22-33`,
`test_text_outbound_e2e.py:117`, `test_element_abc.py:114-134`, and
`test_frame_budget.py:54` — every one constructs a `RecordingRendererFactory`
(`protocol/renderers/recording.py`), a display-capable stand-in, and calls
`elem.render()`. Production elements carry `RAISING_FACTORY` and are never
painted via `elem.render()` (A1, C1). So a green suite coexists with a template
method that would crash if driven the way the render-path design intends.

`test_text_outbound_e2e.py:114-116` even asserts
`decoded._renderer_factory is hub_factory` — but `hub_factory` there is the
test's own `RecordingRendererFactory`, i.e., the injected premise, not the
production `RaisingRendererFactory`. This is exactly the "monkeypatched
premise" failure the project's testing guide warns about: a green test over a
stubbed mechanism.

**Fix:** add a test that drives the real Display receive→paint path (or, at
minimum, asserts that a pickled-then-received ABC element's `_renderer_factory`
is the Display's `ImGuiRendererFactory` after the C1 rebind). Cover the
template method with the production wiring, not a stand-in.

### I2 — MODERATE — the guard-fires test passes only because the path is dead

`test_abc_di_defaults.py:39,55` asserts `elem.render()` raises under
`RAISING_FACTORY`. It passes precisely because the positive paint path is never
taken in production. The negative test is correct but gives false comfort:
nothing proves the guard is correctly *bypassed* on the display tier.

**Fix:** after C1, add the complementary positive test (display-tier element
paints without raising) so the pair covers both branches.

## Suggested paydown sequence

The ordering is dictated by one hard dependency: **the DI truth must be fixed
before the render-path flip, or the first frame crashes.**

1. **DI-truth PR (blocking prerequisite).** Land C1 + C2 (rebind the Display
   factory onto received ABC elements in `_wrap_abc_elements`), correct the
   false docstrings A1 / A2 / A4 / A5 / A6, and add the production-path tests
   I1 / I2. After this PR, `elem.render()` is safe to call on the Display and
   the sentinel guard's promise is real. This unblocks the render-path work.
2. **Render-path-unification PR.** Proceed per
   [render-path-unification-design.md](./render-path-unification-design.md).
   With step 1 landed, the `_paint_element` flip enters `elem.render()` against
   a real factory. A3 and the `renderer.py:22-25` docstring resolve here.
3. **Generalization + cleanup PRs (parallelizable, before more kinds migrate).**
   - E2 / E3 / E4 — replace per-kind enumerations with ABC / typed dispatch.
   - D1 / D2 — OO-ify `messages/scene.py`, kill `str`-with-comment and the
     private reach-around.
   - F2 — typed tooltip Protocol instead of `getattr` probing.
   - G1 / G3 — drop the dead factory state and the stale plan comment.
   - A7 — delete the tombstone, fix the wrapping attribution.
   - D3 / D4 — tighten the decode-boundary and query-handler signatures.
   - H2 — relocate `canonicalize_button_sugar` to a leaf module.
   - F3 — confirm or route the Display-side `model.close()` write.

Steps 1 and 2 are the gate to a clean baseline any new kind can copy. Step 3
retires the remaining OO / coupling / doc debt so the exemplar reads honestly.
