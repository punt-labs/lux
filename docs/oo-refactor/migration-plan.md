# Migration Plan — Domain Model Across All Tiers (Revised 2026-05-23)

**Status:** ACTIVE
**Target:** `docs/architecture/domain-model.md` (the domain north star) and `docs/architecture/io-model.md` (the I/O architecture) and `docs/architecture/x11-model.md` (the process topology)
**Method:** B-amended (see "Methods considered and rejected" below)
**Authority:** This is the executable plan. Mission YAMLs cite PRs from this document; specialist agents (`rmh`, `gvr`, `mdm`, `djb`, `adb`, `kpz`) execute PRs in the order below.

## Why this revision exists

The original migration plan (drafted 2026-05-22) targeted `domain-model.md` as the
north star and sequenced seven PRs (PR 0 through PR 6) to land the domain layer,
migrate the element families onto it family-by-family, then split the display into
its own process. PRs 0, 1, and 2 shipped under that plan.

After PR 2 merged, post-shipment design discussion produced
`docs/architecture/io-model.md` and ADRs **DES-032** (Element Owns Behavior, Not
I/O) and **DES-033** (Renderer and Decoder Families with Asymmetric Cardinality).
Those decisions identified that PRs 1 and 2 made a real but incomplete step toward
the OO target:

- Codec methods (`to_dict` / `from_dict`) were placed ON the Element class as a
  local improvement over module-level helpers, but the same principle that
  forbids `imgui` imports on Element forbids `json`-shaped dict imports on
  Element. Codec belongs in a per-format Decoder family, not on the domain class.
- `render()` does NOT live on the Element class today — it lives on an
  `ElementRenderer` god class that dispatches by `isinstance`. The Composite
  pattern is broken; the template method that should be on `Element` is on a
  separate dispatcher.
- Behavior (`on_click`, `on_drag`, `on_value_change`, etc.) lives on the
  renderer side rather than on the Element. Renderers emit InteractionMessages
  directly. By DES-031 + DES-032, behavior is the Element's responsibility;
  renderers should detect surface-idiom events and call element behavior
  methods.

The remaining PRs are restructured to adopt the io-model architecture as we go,
starting with refactoring the basics family onto it (PRs 3–4), migrating the
inputs family and collapsing the Interaction-routing layer (PR 5), then
bringing the remaining element families onto the same shape (PRs 6–9),
followed by connection-layer cleanup + Encoder family (PR 10), the Observer
subsystem (PR 11), final cleanup (PR 12), and finally the process split (PR 13).

## What's shipped

| PR  | Bead       | GitHub | Status   | Summary |
|-----|------------|--------|----------|---------|
| 0   | `lux-edvm` | #184   | ✅ MERGED | Characterization snapshots + `make snapshot-parity` gate |
| 1   | `lux-b14i` | #186   | ✅ MERGED | Domain layer + basics family migrated (with codec-on-class — to be refactored in PR 3) |
| 2   | `lux-i84j` | #187   | ✅ MERGED | Inputs family migrated (with codec-on-class — to be refactored in PR 5) |

PRs 1 and 2 are productive steps that DO NOT need to be reverted. They
establish the domain layer (`Display`, `Update`, `Event`, `ClientId`, etc.),
the per-class module structure, per-kind renderer classes for basics+inputs in
`display/renderers/`, the `DomainPump` wire-side routing, and the
`Display.interact` Interaction-routing pipeline. The io-model adoption builds
on this scaffolding; it does not throw it away. What changes is the OWNERSHIP
boundary — codec moves off the class, render moves onto the class, behavior
moves onto the class, factories get injected.

## The Bar — non-negotiable invariants

Rules 1–9 are unchanged from the original plan. **Rule 10 (tests arrive
with the code, per commit) is NEW in this revision** — it was implicit
in earlier missions but is now codified after PR 2's review surfaced
tests-in-follow-up-commit patterns that should not recur. Repeated here
for self-containment.

1. **The system stays running at every step.** No flag days. Each PR is
   independently shippable. Existing agents that call `show()` /
   `show_table()` / `show_dashboard()` continue to work without modification
   until the final cleanup PR.

2. **`make check` passes on every commit, not every PR.** The OO ratchet
   must improve or hold; the suppression ratchet must hold or decrease. A
   commit that fails `make check` is a broken commit.

3. **No suppressions to land a PR.** No `# noqa`, no `# type: ignore`, no
   `# pylint: disable`, no `--no-verify`, no editing `.oo-baseline.json` by
   hand. If a suppression is genuinely necessary (e.g., a third-party
   library with no stubs), it must be approved by the operator before the
   PR is opened.

4. **No backwards-compatibility shims that outlive their PR (PL-PP-1).**
   When the new path covers the old one, the old one is deleted in the
   same PR that completes the coverage — not "in a follow-up." Re-exports,
   tombstone comments, "deprecated" aliases are forbidden.

5. **No dead code waiting to be wired (PY-RF-2).** A new class with zero
   callers is a refactoring failure. Infrastructure PRs ship with the
   first consumer that proves the infrastructure works.

6. **Local verification per commit, ship per PR.** Within each PR:
   - `make check` runs after every commit.
   - `code-reviewer` and `silent-failure-hunter` agents run on the diff
     of each commit (or each logical step of commits).
   - `make snapshot-parity` (introduced in PR 0) runs as a CI gate from
     PR 1 onward.
   - Manual smoke test (`make install` + restart `luxd` + exercise the
     affected MCP tools) is run by the agent who owns the PR before the
     PR opens.

7. **The COO does not write code.** Every implementation PR is delegated
   through an ethos mission. Mission YAMLs cite the OO rules verbatim in
   the first 20 lines, with one BEFORE/AFTER example. Worker and evaluator
   are distinct handles per the lux/CLAUDE.md pairing table.

8. **PR granularity ≠ verification granularity.** The verification unit is
   the local step (one transformation, locally reviewed, locally tested).
   The shipping unit is rollback coherence. A PR contains as many verified
   local steps as fit one rollback-coherent unit of work.

9. **No time estimates.** Plans speak in PR count and dependency order.
   Cadence is whatever the work allows.

10. **Tests arrive with the code, per commit.** When a commit adds a new
    Element class, a new Renderer, a new Decoder, a behavior method, or any
    other user-visible production code, the same commit contains the test
    that exercises it. Tests in a separate commit, deferred to a follow-up
    commit, or "to be added in a later commit of this PR" are forbidden.
    Red-green-refactor at commit granularity is the discipline; same-commit
    code-and-test is how it is enforced. The only exception is pure
    documentation / baseline-alignment commits (chore commits with no
    production code change).

## Architecture references (new)

Mission YAMLs from PR 3 onward MUST cite these in the OO-rules block:

- `docs/architecture/io-model.md` — the I/O architecture target.
- `DESIGN.md` DES-031 — Domain Model Across All Tiers (grounding decision).
- `DESIGN.md` DES-032 — Element Owns Behavior, Not I/O (codec moves off the
  class; render moves onto the class via template method; behavior methods on
  Element subclasses; `renderer_factory` + `emit` injected at construction).
- `DESIGN.md` DES-033 — Renderer and Decoder Families with Asymmetric
  Cardinality (per-surface and per-format families, module-level registries,
  1 RendererFactory + N Decoders per Display).
- `DESIGN.md` DES-034 — IPC and Rendering Are Decoupled — Renderer vs Encoder
  Distinction (Encoder family is committed; IPC carries Updates and Events
  only, never render calls; renderer is display-tier; encoder is in every
  shipping tier; shipping strategy whole-tree-vs-diff is a downstream-surface
  property). Mission YAMLs from PR 5 onward MUST cite this for the
  Encoder/Decoder family work that lands in PR 10.
- `DESIGN.md` DES-035 — Handler Routing — Ownership, Client Kind, and Pattern
  Are Three Independent Axes (ownership = "hub" or connection_id; client kind
  = library / wire / LLM agent; handler pattern = deterministic /
  agent-escalation / hybrid; applet author writes tier-blind code). Mission
  YAMLs from PR 5 onward MUST cite this (PR 5 is where the Interaction-layer
  collapses because behavior is on Element and routing is by ownership).
- `DESIGN.md` DES-036 — Observer Pattern at the MCP Boundary (hub is Subject;
  MCP-connected agents are Observers; topic-based subscribe / publish /
  notify; PublishMessage wire kind for in-fabric publishers crossing Lux IPC).
  Mission YAMLs from PR 11 onward MUST cite this for the Observer subsystem.

## Pipeline (revised)

Thirteen PRs total — flat sequential numbering for readability. PRs 0–2
are shipped (above). PRs 3 through 13 are the remaining work, each a
rollback-coherent unit:

| PR | Scope |
|----|-------|
| 3  | io-model foundation + Text (single proving consumer) |
| 4  | Remaining basics (Image, Separator, Progress, Spinner, Markdown) |
| 5  | Inputs family (9 classes) + Interaction-layer collapse |
| 6  | Layout family (Group, Window, TabBar, CollapsingHeader, Tree, Modal) |
| 7  | Graphics — Draw + sub-Composite draw commands |
| 8  | Table family |
| 9  | Plot family |
| 10 | Connection-layer cleanup + Encoder family + SceneManager scope cut + ClientConnected/Disconnected events |
| 11 | Observer subsystem (subscription registry, MCP tools, PublishMessage, in-fabric API, first consumer) |
| 12 | Final cleanup |
| 13 | Process split (x11-model topology) |

### PR 3 — io-model foundation + Text (single proving consumer)

| Field | Value |
|-------|-------|
| **Goal** | Land the io-model infrastructure (Element abstract base with template-method `render()`, `Renderer` / `RendererFactory` Protocols, `Surface` enum, `Renderers` registry, `Decoder` / `DecoderFactory` Protocols, `WireFormat` enum, `Decoders` registry) AND migrate ONE Element — `TextElement` — onto it as the proving consumer. The single-element scope keeps the rollback surface small for the highest-risk PR. PR 4 brings the remaining basics onto the proven infrastructure. |
| **What lands** | (a) **Infrastructure:** new `domain.element` ABC with `render()` template method, `_children()` hook, `__new__(*, renderer_factory, emit, **kwargs)` constructor. New `protocol.renderer` module with `Renderer` Protocol (begin/end for composites, render for leaves). New `protocol.renderer_factory` module with `RendererFactory` callable Protocol, `Surface` enum (IMGUI, RECORDING, NULL), `Renderers` registry. New `protocol.decoder` module with `Decoder` Protocol, `WireFormat` enum (JSON only), `Decoders` registry. (b) **Text migration:** `TextElement` rebuilt on the Element ABC, switches from `@dataclass(frozen=True)` to `__new__`-pattern construction with injected `_renderer_factory` and `_emit`. Codec methods (`to_dict`/`from_dict`) DELETED from `TextElement`. (c) **JSON decoder for Text:** new `JsonTextDecoder` class. `JsonDecoderFactory` class that dispatches by `"kind"` — initially only knows `"text"`, with other kinds deferred to subsequent PRs (each migration adds its decoder). (d) **ImGui renderer factory + Text:** new `ImGuiRendererFactory` class that owns shared state (widget_state, texture_cache, emit channel) and dispatches by Element type. `ImGuiTextRenderer` refactored to implement the new `Renderer` Protocol. (e) **Recording renderer:** one generic `RecordingRenderer` class that captures `(op, kind, id)` tuples uniformly for any Element (op ∈ {render, begin, end}). Recording is a single class, not per-kind, because the recorded shape is type-agnostic. (f) **Null renderer:** one generic `NullRenderer` class — pure no-op for any Element. (g) **Wire-layer integration:** the connection layer uses `Decoders.getDecoderFor(WireFormat.JSON, renderer_factory, emit)` for the Text path. Other element kinds continue through the existing `element_from_dict` until they migrate. (h) **Display server integration:** the render loop calls `scene_root.render()` via the Element template method for any Text element. Non-Text elements continue through the existing `ElementRenderer`. (i) **WidgetValueProvider DELETED.** The PR 2 Protocol that lived as a SceneManager dispatch contract is gone — widget state is an Element-internal concern mediated through behavior methods (which Text doesn't have, so this is purely a deletion in PR 3). PR 4's inputs migration uses the Element-internal pattern; nothing dispatches on this Protocol from PR 3 onward. (j) **First headless render test for Text** using the Recording renderer. |
| **Why infra + Text in one PR** | The Bar §5 (PY-RF-2): infrastructure ships with a consumer. Text is the consumer. Text is the simplest possible element — no children, no behavior, just `surface.text(content, style)` — so it gates the design without confounding the review with kind-specific complexity. |
| **Why Text first** | Smallest blast radius. If the infrastructure design has flaws, they surface on one element before five more get built on top. The other basics are mechanical replications of the Text pattern, which PR 4 executes. |
| **Internal commit sequence (required)** | Per The Bar §5 and §10, code + test land together; infrastructure ships with a consumer (the consumer can be a test fixture for genuinely-generic infra like RecordingRenderer). (i) **RecordingRenderer + NullRenderer + their tests** — these are genuinely generic (Element-kind-agnostic); the test that drives them with a synthetic Element subclass is their consumer. No production code touched yet. (ii) **Element ABC + Renderer Protocol + RendererFactory + Surface + Renderers registry + Decoder Protocol + WireFormat + Decoders registry — first TextElement test (RED).** Write a failing test for TextElement on the ABC using the RecordingRenderer from (i). No production TextElement refactor yet; test fails because the io-model TextElement doesn't exist. (iii) **TextElement refactored onto ABC + JsonTextDecoder + ImGuiRendererFactory + ImGuiTextRenderer — test from (ii) goes GREEN.** Delete the PR-1 codec methods from TextElement; delete the PR-1 ImGuiTextRenderer's old shape. (iv) **WidgetValueProvider deletion** — separate commit, cleanly removes the Protocol and its sole call site in scene/manager. Tests for any element that used WidgetValueProvider get updated to use behavior-on-Element instead (basics had no such elements, so this is mostly test-fixture cleanup). (v) **Wire-layer and display-server routing for Text** — connection layer uses `Decoders.getDecoderFor(WireFormat.JSON, NullRendererFactory(), emit_to_owner)` for non-display callers when wiring up Text; ImGui server uses `Decoders.getDecoderFor(WireFormat.JSON, ImGuiRendererFactory(...), emit_back_to_originator)` for its inbound path. Non-Text elements continue through the existing `element_from_dict`. The `renderer_factory` argument to `getDecoderFor` is `NullRendererFactory()` in any non-display tier — this constraint is documented now but only exercised once the process split (PR 13) creates non-display tiers. Until then PR 3 runs single-tier and only the ImGui factory is wired. (vi) **Old TextElement scaffolding deletion** — verify no remaining references; delete any text-specific dispatch in element_renderer.py. Each commit passes `make check` + `make snapshot-parity` + local code-reviewer + silent-failure-hunter before the next. |
| **What does NOT land** | The other 5 basics (PR 4), inputs (PR 5), layout (PR 6), graphics/table/plot (PRs 7/8/9), HTML renderer (deferred — no consumer), Encoder family (lands PR 10 with its first consumer). |
| **Ratchet effect** | Element ABC and the Protocol/registry modules add new small files. JsonTextDecoder + RecordingRenderer + NullRenderer add new small files. TextElement loses its codec methods (smaller). The `ElementRenderer` god class is partially gutted (Text dispatch removed) but persists for other kinds. WidgetValueProvider deletion reduces scene/manager. Net: more files, smaller files. |
| **Worker / Evaluator** | `rmh` (Python implementation) / `gvr` (Python evaluation). `rej` consulted on the template-method Composite realization and on `WidgetValueProvider` deletion. |
| **Acceptance** | `make snapshot-parity` passes (byte-identical wire output for Text — codec moved but produces the same bytes). `make check` clean. `TextElement` instantiates via `TextElement(renderer_factory=..., emit=..., id=..., content=..., ...)` and renders via `elem.render()` template. Recording renderer test for Text passes. ImGui smoke test renders Text identically to PR 2 baseline. Grep verifies zero `from_dict` / `to_dict` methods on `TextElement` and zero references to `WidgetValueProvider` anywhere in `src/`. The 5 remaining basics (Image, Separator, Progress, Spinner, Markdown) and all inputs/layout/etc. still use the pre-io-model shape — they migrate in PR 4 and PRs 5+ respectively. |

### PR 4 — remaining basics onto io-model

| Field | Value |
|-------|-------|
| **Goal** | Migrate the remaining 5 basics (Image, Separator, Progress, Spinner, Markdown) onto the io-model infrastructure proven by PR 3. Mechanical replication of the Text pattern. |
| **What lands** | (a) 5 Element subclasses on the Element ABC. (b) 5 `JsonImageDecoder` / `JsonSeparatorDecoder` / etc., registered with the `JsonDecoderFactory`. (c) 5 ImGui renderer classes refactored to the new `Renderer` Protocol. (d) 5 headless tests via the existing Recording renderer (single generic class — no new Recording classes needed). (e) Wire-layer extension: connection-side decoder now handles all 6 basics. Display-server extension: render loop handles all 6 basics via the Element template method. (f) Old codec methods + ElementRenderer dispatch entries DELETED for each migrating kind. |
| **Internal commit sequence (required)** | (i) Image end-to-end (Element + JsonDecoder + ImGui renderer + headless test + old-scaffolding deletion — all in one commit per The Bar §5/§10). (ii) Separator end-to-end. (iii) Progress end-to-end. (iv) Spinner end-to-end. (v) Markdown end-to-end. Each commit passes `make check` + `make snapshot-parity` + local review before the next. |
| **What does NOT land** | Inputs (PR 5), layout (PR 6), graphics/table/plot (PRs 7/8/9), Encoder family (PR 10), Observer (PR 11), HTML renderer. |
| **Ratchet effect** | Continued: codec deletion shrinks Element files; new per-kind decoder classes add small files; ElementRenderer god class shrinks further. |
| **Worker / Evaluator** | `rmh` / `gvr`. |
| **Acceptance** | `make snapshot-parity` passes for all 6 basics. `make check` clean. Every basics class on the Element ABC. Recording renderer tests cover all 6 basics. ImGui smoke test renders Frame 1 (Basics) identically to PR 2 baseline. Grep verifies zero `from_dict`/`to_dict` on any basics Element class. The `ElementRenderer` god class no longer dispatches any basics kind. |

### PR 5 — io-model inputs refactor

| Field | Value |
|-------|-------|
| **Goal** | Migrate every input-family Element (Button, Slider, Checkbox, Combo, InputText, InputNumber, Radio, ColorPicker, Selectable — 9 classes) onto the io-model infrastructure established in PRs 3–4. The `WidgetValueProvider` Protocol is already deleted (PR 3); this PR uses behavior-on-Element for widget state. |
| **What lands** | (a) Each of the 9 input Element classes refactored: inherits from Element ABC, switches to `__new__`-pattern construction with `renderer_factory` + `emit` injection, gains behavior methods (`ButtonElement.on_click`, `SliderElement.on_value_change`, `CheckboxElement.on_toggle`, `ComboElement.on_select`, `InputTextElement.on_change`, `RadioElement.on_select`, `InputNumberElement.on_change`, `ColorPickerElement.on_change`, `SelectableElement.on_toggle`). Codec methods (`to_dict`/`from_dict`) DELETED. (b) 9 new `Json{Kind}Decoder` classes registered with the `JsonDecoderFactory`. (c) 9 ImGui renderer classes refactored — they stop emitting InteractionMessages directly; instead they call `self._elem.on_click()` / `on_value_change()` / etc. when the surface detects the action. The Element behavior method decides what (if anything) to emit. (d) Recording renderer test for each input — assert "calling `elem.on_click()` emits InteractionMessage with action X." Recording renderer itself is generic (shipped PR 3) — no new renderer classes. (e) **Interaction-routing layer deletion (step iv expanded):** the entire round-trip through `Display.interact` collapses because behavior is now on Element. Specifically, the following are DELETED in PR 5: `src/punt_lux/domain/interaction.py` (ButtonClicked and Interaction sum type), `src/punt_lux/domain/interaction_event.py` (ButtonPressed event), `Display.interact()` method and all its tests, `DomainPump.route_interaction()` method and its `_is_button_click()` helper, the `ButtonPressed` member of the domain `Event` union, the wire-side `_emit_event → route_interaction` plumbing in `display/server.py`. After PR 5, the click flow is: `ImGuiButtonRenderer.render()` → `imgui.button(...) → True` → `self._elem.on_click()` → `self._emit(InteractionMessage(...))` directly to the wire emit channel. One round-trip, no Interaction sum type, no Display.interact. (f) Old `ElementRenderer` inputs branches and old codec scaffolding for inputs deleted. |
| **Why this PR exists** | Same as PRs 3–4's reason for basics: PR 2's codec-on-class is a productive step but not the target. Inputs are the family where behavior matters most (click, value-change), so io-model adoption brings the most user-visible payoff. |
| **Internal commit sequence (required)** | Per The Bar §5/§10, code + test land together. (i) Button end-to-end (Element on ABC + on_click behavior + JsonButtonDecoder + refactored ImGuiButtonRenderer calling elem.on_click() + headless behavior test + old ButtonElement codec deletion + old ButtonRenderer click-emission code deletion — all one commit). (ii) Slider end-to-end (value-change pattern). (iii) Checkbox. (iv) Combo. (v) InputText. (vi) InputNumber. (vii) Radio. (viii) ColorPicker. (ix) Selectable. (x) **Interaction-layer deletion commit:** delete `domain/interaction.py`, `domain/interaction_event.py`, `Display.interact()`, `DomainPump.route_interaction()`, `_is_button_click()`, narrow the Event union to remove ButtonPressed, simplify `_emit_event` in server.py. All affected tests updated in the same commit. This commit is large but is a single coherent deletion — nothing partial works in between. (xi) Delete remaining inputs-branch code in `ElementRenderer`. Each commit passes `make check` + `make snapshot-parity` + local review before the next. |
| **What does NOT land** | Layout (PR 6), graphics/table/plot (PRs 7/8/9), Encoder family (PR 10), Observer (PR 11), HTML / other surfaces. |
| **Ratchet effect** | Codec deletion shrinks 9 Element files; behavior methods grow them modestly. Net positive on per-file scores. Interaction-layer deletion shrinks `domain_pump.py`, `display/server.py`, `domain/display.py` substantially. The `ElementRenderer` god class no longer dispatches any inputs kind by PR 5 end. |
| **Worker / Evaluator** | `rmh` / `gvr`. `dna` (interaction design) consulted on Element behavior method shape. |
| **Acceptance** | `make snapshot-parity` passes. Every input class on the new Element ABC. Behavior methods are testable via Recording renderer and via direct `elem.on_click()` calls in unit tests. ImGui smoke test: every input kind interactable (click button, drag slider, type in InputText, etc.), values reach the agent via `recv()` with the same wire shape as before. **After commit (i), Button's click path does NOT transit `Display.interact`** — verified by a test that mocks/inspects the call stack and confirms `imgui.button → elem.on_click → self._emit` is the path, with no `Display.interact` frame between them. Same check for Slider value-change after commit (ii). Grep verifies zero `to_dict`/`from_dict` on any input class, zero references to `ButtonClicked` / `ButtonPressed` / `Display.interact` / `DomainPump.route_interaction` / `_is_button_click` anywhere in `src/`. |

### PR 6 — layout family

| Field | Value |
|-------|-------|
| **Goal** | Migrate the layout family — Group, Window, TabBar, CollapsingHeader, Tree, Modal (6 classes) — in io-model shape from the start. Layout is where the Composite pattern proves itself, because every layout element is a real composite with children. |
| **Depends on** | PR 5. The Reparent test (acceptance below) moves a `ButtonElement` between Groups; `ButtonElement` is io-model-shape only after PR 5 ships. |
| **What lands** | (a) 6 new layout Element classes on the io-model ABC, each overriding `_children()` to return its children. Behavior methods where relevant: `WindowElement.on_close` / `on_minimize` / `on_maximize` / `on_move` / `on_resize`; `TabBarElement.on_tab_select`; `CollapsingHeaderElement.on_toggle`; `ModalElement.on_close`; `TreeElement.on_node_expand` / `on_node_collapse` / `on_node_click`. (b) 6 JSON decoder classes that recursively decode children via the registry. (c) 6 ImGui renderer classes implementing `begin()` and `end()` (the composite bracketing — `imgui.begin_window(...)` / `imgui.end_window()`, etc.). Renderers stop calling SceneManager state mutations directly — window position/size changes flow through the Element's on_move/on_resize behavior, which emits an event the application can subscribe to. (d) Recording renderer continues to handle composites uniformly via begin/end — no new Recording classes. (e) Domain support: `ReparentElement` and `ReplaceElement` Update kinds added to the domain `Update` sum. Cycle detection enforced in `Display.apply` (PY-EH-1). `CycleError` event. These land alongside the Group migration (their first consumer), not in a standalone commit. (f) Old `SceneManager.handle_scene` layout-branch code and old `ElementRenderer` layout-branch code deleted as each kind migrates. |
| **Internal commit sequence (required)** | Per The Bar §5/§10, infrastructure ships with its first consumer in the same commit. (i) **Group + domain additions:** add ReparentElement, ReplaceElement, CycleError to the domain AND migrate Group end-to-end (Element + JsonDecoder + ImGui begin/end renderer + Recording test + Reparent test + Cycle test — all one commit). The domain additions have a consumer (Group accepts ReparentElement / ReplaceElement; Group children can trigger CycleError). PY-RF-2 satisfied. (ii) TabBar end-to-end. (iii) CollapsingHeader end-to-end. (iv) Window end-to-end (most behavior — close/minimize/maximize/move/resize, each with a behavior test). (v) Tree end-to-end (recursive composite, with on_node_expand/collapse/click). (vi) Modal end-to-end. (vii) Delete remaining old layout paths from SceneManager and ElementRenderer. Each commit passes `make check` + `make snapshot-parity` + local review before the next. |
| **Ratchet effect** | Composite pattern fully realized on the Element side. `Display` enforces structural invariants 4 and 5 from `domain-model.md`. `element_renderer.py` shrinks further. |
| **Worker / Evaluator** | `rmh` / `gvr`. `rej` consulted on Composite pattern realization across leaves and composites. |
| **Acceptance** | `make snapshot-parity` passes. Nested groups, tabbed scenes, collapsing sections, modals render correctly. **Reparent test (depends on PR 5 for ButtonElement):** move a `ButtonElement` from one `GroupElement` to another via `Display.apply(ReparentElement(...))`, observe the resulting events, verify the rendered tree reflects the new parent. **Cycle test:** attempt to add a Group as a child of one of its descendants, verify `CycleError` event and refused Update with no state change. Recording renderer tests assert the composite tree shape end-to-end (begin/render/end sequence for nested layouts). |

### PR 7 — graphics family (Draw)

| Field | Value |
|-------|-------|
| **Goal** | Migrate `DrawElement` and its draw-command sub-Composite onto the io-model. Draw is structurally distinct from the other 23 element kinds because it carries an internal sub-tree of draw commands (Circle, Rect, Polyline, BezierCubic, etc.) that themselves form a Composite. |
| **What lands** | (a) `DrawElement` on the Element ABC. The draw-commands sub-tree gets its own per-kind Decoder/Renderer treatment within the Draw family — Circle, Rect, Polyline, Triangle, BezierCubic, Line, TextGlyph each get a small Renderer in `display/renderers/draw/`. (b) `JsonDrawDecoder` that recursively decodes draw commands. (c) `ImGuiDrawRenderer` refactored to io-model shape — uses the ImGui draw list for low-level primitives. (d) Recording renderer captures draw-command tuples. (e) Headless tests for each draw-command kind via Recording. (f) Old `SceneManager.handle_scene` Draw branch and old `ElementRenderer` Draw branch deleted. |
| **Internal commit sequence (required)** | (i) DrawElement on ABC + JsonDrawDecoder + ImGuiDrawRenderer skeleton + Recording test for empty Draw (no commands). (ii) Per-draw-command migrations in commits (Circle, Rect, Polyline, Triangle, BezierCubic, Line, TextGlyph — each a separate commit with its renderer + test). (iii) Old Draw paths deletion. |
| **Ratchet effect** | Sub-Composite (draw commands) realized within the larger Element Composite. `element_renderer.py` shrinks. |
| **Worker / Evaluator** | `rmh` / `gvr`. `kpz` (perf) consulted on draw-list interaction with ImGui. |
| **Acceptance** | `make snapshot-parity` passes. Drawing a diagram with mixed draw commands renders identically to PR 6 baseline. Recording renderer test for every draw-command kind. |

### PR 8 — table family (TableElement)

| Field | Value |
|-------|-------|
| **Goal** | Migrate `TableElement` (with its columns, rows, filters, detail panel) onto the io-model. Table has the most state and the richest behavior surface of any element. |
| **Depends on** | PR 6 — TableElement's detail panel can contain arbitrary child Elements (typically layout containers); those children must already be on the io-model. PR 6 (layout) is the dependency. If the table cells themselves can only hold leaf basics + inputs (PR 3/4/5), the detail-panel dependency on PR 6 is the binding one. |
| **What lands** | (a) `TableElement` on the ABC with behavior methods: `on_row_select`, `on_filter_change`, `on_column_sort`, `on_detail_open`, `on_detail_close`. (b) `JsonTableDecoder` that handles columns, rows, filters, detail-panel config. (c) `ImGuiTableRenderer` refactored to io-model shape — the existing TableRenderer's filter/search/detail logic moves under the new ImGui per-kind renderer; the Element holds the column/row data and behavior methods. (d) Recording renderer captures table-render and per-row-render. (e) Headless tests for: row selection, filter change, column sort, detail panel open/close. (f) Old `SceneManager` Table branch and old TableRenderer scaffolding deleted. |
| **Internal commit sequence (required)** | (i) TableElement on ABC + JsonTableDecoder + ImGuiTableRenderer + basic Recording test (one row, no filter). (ii) Filter behavior + test. (iii) Row-select behavior + test. (iv) Column-sort behavior + test. (v) Detail-panel behavior + tests. (vi) Old Table paths deletion. |
| **Ratchet effect** | `element_renderer.py` shrinks further. The standalone `table_renderer.py` either folds into the Table family or stays as a low-level helper invoked by `ImGuiTableRenderer`. |
| **Worker / Evaluator** | `rmh` / `gvr`. `edt` (information design) consulted on table behavior shape. |
| **Acceptance** | `make snapshot-parity` passes. Filterable table with detail panel renders identically to PR 7 baseline. All five behavior methods testable via Recording. |

### PR 9 — plot family (PlotElement)

| Field | Value |
|-------|-------|
| **Goal** | Migrate `PlotElement` (with its series, axes, zoom/pan state) onto the io-model. Plot has perf-critical paths that need careful evaluator attention. |
| **Depends on** | None additional. Plot is a leaf composite (it has series internally, but series are draw-command-shaped, not arbitrary Elements). No tooltip-as-child or other container relationship. Plot can ship independently of PRs 7/8. |
| **What lands** | (a) `PlotElement` on the ABC with behavior methods: `on_zoom`, `on_pan`, `on_axis_change`, `on_series_toggle`. (b) `JsonPlotDecoder` that handles series, axes, plot config. (c) `ImGuiPlotRenderer` refactored — uses imgui_bundle.implot for rendering. The plot's perf budget (frame time per series, per data point) is preserved. (d) Recording renderer captures plot-render + per-series-render. (e) Headless tests for behaviors. (f) Verify `OwnershipError`, `DuplicateIdError`, `PropertyTypeError` cover all paths now that all 24 kinds are on the domain. (g) Old `SceneManager` Plot branch and old plot scaffolding deleted. NOTE: `ClientConnected` / `ClientDisconnected` Events and the disconnect cascade are NOT in this PR — they move to PR 10 where the connection lifecycle is the natural home (this PR is element-family migration, not connection-layer work). |
| **Internal commit sequence (required)** | (i) PlotElement on ABC + JsonPlotDecoder + ImGuiPlotRenderer + basic Recording test (one series, default axes). (ii) Per-behavior migrations (zoom, pan, axis-change, series-toggle) each as separate commit with test. (iii) Old Plot paths deletion. |
| **Ratchet effect** | All 24 element kinds now on the io-model. `method_ratio` at or near 0.80 target. `element_renderer.py` is empty or near-empty — slated for full deletion in PR 12. |
| **Worker / Evaluator** | `rmh` / `gvr`. `kpz` (perf) consulted on per-series rendering hot path; `edt` on axis behavior. |
| **Acceptance** | `make snapshot-parity` passes. Plot with multiple series renders identically to PR 8 baseline (table baseline). Frame time for a 1000-point series is within 10% of pre-migration. All composite-invariant tests (cycle, ownership, duplicate-id, type-mismatch) pass for every relevant element kind. |

### PR 10 — connection-layer & DomainPump cleanup + Encoder family

| Field | Value |
|-------|-------|
| **Goal** | After all 24 kinds are on io-model (PRs 3–9), simplify the connection layer and `DomainPump`, and introduce the symmetric Encoder family. Events generated by `Display.subscribe(...)` need to flow back out to clients in their connection format (JSON today); this is the Encoder family's first production consumer (PY-RF-2). Also lands the `ClientConnected` / `ClientDisconnected` Events with cascade per `domain-model.md` invariant 7 — connection lifecycle is the natural place for them. |
| **What lands** | (a) `DomainPump.route` logic simplified — the basics-only / inputs-only routing predicate is gone; every scene routes through Display.apply. (b) Connection layer adopts the io-model decoder lifecycle: per-connection format negotiation (single-arm `match WireFormat.JSON` today; second arm added when a second format ships — do not over-build the negotiator). (c) **Encoder family introduced:** new `protocol.encoder` module with `Encoder` Protocol, `Encoders` registry, `JsonEncoderFactory` with per-kind `JsonTextEncoder`, `JsonButtonEncoder`, … classes (24 per-kind encoders). Each connection gets an Encoder matched to its negotiated format. Events from `Display.subscribe` are encoded and pushed back to the originating client (and to subscribers per ownership) — this is the Encoder's first production consumer. (d) `ClientConnected` / `ClientDisconnected` Events added to the domain Event union; emitted on connect/disconnect with the disconnect cascade per `domain-model.md` invariant 7 (orphan elements removed; downstream subscribers notified). Encoded via the new Encoder family on each client connection. (e) **SceneManager scope cut explicitly:** SceneManager **retains** `_scene_order`, `_active_tab`, `_frames`, `_focus_frame_id`, `_scene_to_frame`, `_scene_to_owner`, `_dirty_windows`, `close_frame()`, frame-lifecycle methods (these are UI-organization concerns, not domain concerns). SceneManager **loses** `_scenes: dict[str, SceneMessage]` (scene storage moves to `Display`), `handle_scene()`, `handle_framed_scene()`, `apply_update()`, `replace_scene()`, `_scene_widget_state` (widget state is Element-internal post-PR-3). The `_widget_value` helper is already gone (deleted in PR 3 with WidgetValueProvider). |
| **What does NOT land** | The Observer subsystem (PR 11). The process split (PR 13). HTML / msgpack / additional surfaces or formats (no consumer beyond JSON yet). |
| **Internal commit sequence (required)** | Per The Bar §5/§10, code + test land together; infra ships with first consumer. (i) **DomainPump simplification:** remove basics/inputs routing predicate; all scenes go through Display.apply; tests assert single path. (ii) **Connection-layer decoder lifecycle:** per-connection negotiation slot (single-arm JSON); test covers connect, format-detect, decoder selection. (iii) **Encoder family + first consumer (combined commit per PY-RF-2):** Encoder Protocol, Encoders registry, JsonEncoderFactory, 24 per-kind Json…Encoder classes, integration with Display.subscribe so Events flow back to clients via Encoder; Event round-trip test for every Event kind. (iv) **ClientConnected / ClientDisconnected Events:** added to domain Event union; emitted on connect/disconnect; cascade tested. (v) **SceneManager scope cut:** delete `handle_scene`, `apply_update`, `replace_scene`, `_scene_widget_state`, `_scenes`; tests for the retain-list behaviors. Each commit passes `make check` + `make snapshot-parity` + local review before the next. |
| **Ratchet effect** | Connection layer (`server.py`, `domain_pump.py`) shrinks substantially. `SceneManager.handle_scene` / `apply_update` / `replace_scene` deleted. The `ElementRenderer` god class is fully gone by this point (deleted in PR 12 final cleanup, or earlier as each family deletes its dispatch entries). Encoder family adds new small files. |
| **Worker / Evaluator** | `rmh` / `gvr`. `mdm` (CLI specialist) consulted on connection lifecycle. `djb` consulted on Encoder safety (no Pickle, JSON-shape only). |
| **Acceptance** | `make snapshot-parity` passes. Connection-layer tests cover format-negotiation slot (single-arm today; arm-adding mechanism tested). Encoder tests cover Event round-trip for every Event kind including ClientConnected/Disconnected. Cascade test: disconnect cascade removes orphan elements and emits the expected ElementRemoved + ClientDisconnected sequence. Grep verifies: no remaining `isinstance(elem, KindElement)` branches in `scene/manager.py` or `server.py`; SceneManager retains only its named retain-list; no `handle_scene` / `apply_update` / `replace_scene` methods remain on SceneManager. |

### PR 11 — Observer subsystem (subscription registry, MCP tools, PublishMessage, in-fabric API, first consumer)

| Field | Value |
|-------|-------|
| **Goal** | Land the Observer pattern at the MCP boundary per DES-036. Hub becomes a Subject; MCP-connected agents become Observers; topic-based subscribe/publish/notify. Ships with a real production consumer (PY-RF-2): the existing `recv()` polling tool is replaced by Observer-push from the hub. |
| **What lands** | (a) **Subscription registry** in hub: `{topic: str → set[connection_id]}`. Thread-safe; cleared per-connection on disconnect (cascade). (b) **MCP tools**: `subscribe(topic)`, `unsubscribe(topic)`, `publish(topic, payload)`. Standard FastMCP tool registrations. Authorization: subscribe/unsubscribe are open; publish is open (every connection can publish; topic vocabulary is convention). (c) **MCP server-push notification path**: hub serializes `observed(topic, payload)` JSON-RPC notification via the MCP server's send_notification API; agent runtime delivers to the LLM. (d) **`PublishMessage` wire kind** added to the Encoder/Decoder family from PR 10: when a separate-process applet calls `hub.publish(...)`, the call serializes as a PublishMessage over Lux IPC; hub receives, decodes, runs the same fan-out as the MCP path. (e) **In-fabric Python API**: `hub.publish(topic, payload)` and `hub.subscribe(topic) -> Subscription` for in-process callers. (f) **First production consumer (mandatory PY-RF-2):** the existing `recv()` polling tool (Claude Code currently polls this for pending interaction events) is reimplemented as a subscriber. Agents connecting via MCP automatically subscribe to `interaction.*` topics on connect (via a new auto-subscribe convention or explicit subscribe call); the hub publishes `interaction.<element_id>` on each routed InteractionMessage, the agent receives via push. The polling-shaped `recv()` tool is retained for one PR as a backward-compat shim but is deprecated in PR 12's cleanup. |
| **What does NOT land** | The process split (PR 13). Topic vocabulary standardization (open convention). Durable subscriptions across reconnects (deferred). |
| **Internal commit sequence (required)** | Per The Bar §5/§10. (i) **Subscription registry + in-fabric API + tests:** registry data structure, `hub.publish` / `hub.subscribe` in-process implementation, unit tests for subscribe/unsubscribe/publish lifecycle including disconnect-cascade cleanup. RecordingObserver test fixture acts as a synthetic subscriber. (ii) **MCP tools + server-push integration + first consumer (combined commit per PY-RF-2):** subscribe/unsubscribe/publish FastMCP tool definitions, MCP server-push notification wiring, recv()-to-subscribe migration for at least one agent-driven event class. Test asserts an MCP-connected agent receives `observed(topic, payload)` notifications on the right topic. (iii) **PublishMessage wire kind:** add PublishMessage to the Encoder/Decoder family from PR 10; applet→hub publish flows over Lux IPC; tests for in-fabric publisher reaching MCP-connected subscriber via the cross-protocol bridge. Each commit passes `make check` + `make snapshot-parity` + local review before the next. |
| **Ratchet effect** | New small files (registry, MCP tool definitions, PublishMessage class). Existing recv-polling tool gains a subscriber-side alternative; deprecation note on the polling path. |
| **Worker / Evaluator** | `rmh` / `gvr`. `mdm` (CLI specialist) consulted on MCP tool surface. `djb` consulted on the Observer subscription model (no privilege escalation through subscribe; payload sanitation if untrusted senders are ever supported). |
| **Acceptance** | `make snapshot-parity` passes. Observer subsystem tests cover: subscribe/unsubscribe lifecycle, publish fans out to all subscribers, in-fabric publisher and MCP-connected agent receive equivalent payloads, unsubscribed publish is a no-op (with debug-level log), disconnect cleans subscription registry, PublishMessage round-trips applet → hub. The `recv()`-to-subscribe migration is exercised end-to-end (an MCP-connected agent receives an interaction event via push, without polling). |

### PR 12 — final cleanup

| Field | Value |
|-------|-------|
| **Goal** | Delete every remaining old-path code, every transitional shim, every dead reference to the pre-io-model architecture. The codebase becomes purely io-model with no historical residue. |
| **What lands (code deletion commits)** | (a) `SceneMessage` whole-scene wire path deleted (replaced by Update-based decoder flow from PR 10). (b) `SceneManager` legacy methods deleted (anything not in PR 10's retain list). (c) `ElementRenderer` god class deleted entirely. (d) `recv()` polling tool deleted now that PR 11's Observer push has subsumed it (the recv backward-compat shim from PR 11 retires here). (e) Any tombstone comments, re-exports, deprecation shims removed. (f) Old per-kind module-level codec helpers and re-exports removed from `protocol/elements/`. |
| **What lands (doc-edit tail commit, separate from code deletion)** | A single trailing commit updates the documentation to reflect the final state: `docs/architecture/system.tex` is updated (the system architecture description follows the new I/O model — Decoder, Element, Renderer instead of the old per-kind dispatch); `docs/oo-refactor/resume.md` records the final OO scores. This commit contains NO source code changes — it competes for review attention only with itself. |
| **Internal commit sequence (required)** | (i) Delete `SceneMessage` whole-scene wire path and its callers. (ii) Delete `SceneManager` legacy methods. (iii) Delete `ElementRenderer` god class. (iv) Sweep `protocol/elements/` for leftover module-level helpers and re-exports; delete. (v) Sweep for tombstone / deprecation / re-export comments; delete. (vi) Single doc-edit commit updating `system.tex` and `resume.md`. Each code-deletion commit passes `make check` + `make snapshot-parity` + local review before the next. The doc commit only needs the markdown / latex lint gates. |
| **Ratchet effect** | `method_ratio` definitively ≥ 0.80. `module_size` for the formerly major files (`server.py`, `element_renderer.py` — now gone, `domain_pump.py`) at or below 300. `classes_per_module` ≤ 3 throughout. |
| **Worker / Evaluator** | `rmh` / `gvr`. `djb` (security) consulted on the audit of removed code paths to confirm no input-validation logic is lost in the deletion. |
| **Acceptance** | `make snapshot-parity` passes. Full MCP surface exercised. OO ratchet shows targets met. Zero dead code remains. `docs/architecture/system.tex` reflects the io-model architecture verbatim — no references to deleted code paths. |

### PR 13 — process split (x11-model topology)

| Field | Value |
|-------|-------|
| **Goal** | Realize the x11-model topology — `lux-display` runs as a separate process from `luxd`, using the JSON Decoder and Encoder families (already shipped) at the IPC boundary. |
| **What lands** | (a) **Two `Display` instances:** `hub_display` in `luxd` (authoritative writer) and `wire_display` in `lux-display` (read-only mirror, drives the ImGui renderer). Each constructed at process startup with appropriate factories — `wire_display` uses `ImGuiRendererFactory`; `hub_display` uses `NullRendererFactory`. (b) **IPC transport:** Unix socket at `~/.lux/display.sock` (configurable). Bytes are JSON (default). `luxd`'s wire-out path constructs a `JsonEncoderFactory(...)` instance; `lux-display`'s wire-in path constructs a `JsonDecoderFactory(...)` instance. Both are existing classes from PR 3 / PR 10 — verified by grep showing zero new Decoder/Encoder/Renderer/Encoder-family subclasses in the PR 13 diff. (c) **Supervision model:** `luxd` spawns `lux-display` as a subprocess on startup, monitors its lifecycle, restarts on crash with exponential backoff (max 5 retries in 60s, then surface error). On `lux-display` crash, `luxd` retains `hub_display`'s state and re-pushes the full scene tree on respawn so the user's session survives. (d) **launchd / systemd integration:** `lux-display`'s lifecycle is owned by `luxd`, not by the OS service manager. The OS service manager owns `luxd` only. New plist for macOS launchd (`com.puntlabs.luxd.plist`) and systemd unit for Linux (`luxd.service`). (e) **Single-process test toggle:** `LUX_DISPLAY_IN_PROCESS=1` environment variable (or equivalent CLI flag) instructs `luxd` to instantiate `wire_display` in-process instead of spawning `lux-display` as a subprocess. The `Display` instance, factories, and Element classes are unchanged; only the wiring differs. This preserves the single-runtime test requirement from `domain-model.md` §"Testability". (f) **Discovery:** when an applet (or other Lux client) connects to `luxd`, it does not need to know `lux-display` exists. The hub is the single entry point; `lux-display` is an internal-to-`luxd` implementation detail of "where rendering happens." |
| **Why deferred to last** | The process split is mechanical IF the in-process architecture is right. By PR 12 the in-process architecture is fully io-model with both Decoder and Encoder families operational; the process split becomes "instantiate the same Element ABC, the same factories, the same registries on each side of the IPC boundary; the IPC boundary is just one more Decoder/Encoder pairing." This is the proof that the operator's design invariant ("objects and message passing become trivially equal to IPC calls") holds. |
| **Why no new infrastructure** | The Encoder family lands in PR 10 with its first consumer (Events to clients). PR 13 reuses it for cross-process IPC — same JSON shape, different transport. No new code families are introduced in PR 13; only process-management and IPC-transport plumbing. |
| **Internal commit sequence (required)** | (i) **In-process test toggle:** add the `LUX_DISPLAY_IN_PROCESS` env-var path that wires `wire_display` inside `luxd`'s process. Tests cover both modes (in-process and stub for soon-to-arrive subprocess). (ii) **IPC transport:** Unix socket setup; serialization via existing JsonEncoder/Decoder; integration test pushes a scene tree across the socket within one process and asserts identity. (iii) **Subprocess spawn + supervision:** `luxd` spawns `lux-display`; basic lifecycle (start, healthcheck, terminate); test asserts subprocess starts, accepts a scene, terminates cleanly. (iv) **Crash recovery:** kill subprocess; supervisor respawns; full scene re-pushed; test asserts session continuity. (v) **launchd / systemd units:** plist and service file added; install scripts updated. (vi) **Discovery / connection ergonomics:** verify applets connect to `luxd` only, never to `lux-display` directly. |
| **Ratchet effect** | Architectural. `Display` is exercised in both single-process (tests) and multi-process (production) modes — proves the topology decoupling. |
| **Worker / Evaluator** | `adb` (infra) / `mdm` (process model). `djb` reviews the IPC trust boundary. `kth` (cloud-native) consulted on the supervision/respawn model. |
| **Acceptance** | `lux-display` runs as a child of `luxd`. `LUX_DISPLAY_IN_PROCESS=1` runs both in one process for tests. `make snapshot-parity` passes in both modes. Local smoke test: kill `lux-display`, `luxd` re-spawns it within backoff window, scenes recover from `hub_display`'s state, user's session continues. No new Decoder/Encoder code introduced — verified by grep on the diff (zero hits for new `Json…Encoder` or `Json…Decoder` classes). |

## Verification discipline

Unchanged from the original plan. Repeated here for self-containment.

Every PR follows this loop. The loop is the contract.

1. **Read this document, the relevant ADRs in `DESIGN.md`, and
   `domain-model.md` / `io-model.md` / `x11-model.md`.**
2. **Author a mission YAML** that cites the OO rules + DES-031/032/033 +
   io-model.md in the first 20 lines with one BEFORE/AFTER example. The
   YAML lives at `.tmp/missions/<pr-name>.yaml`.
3. **Dispatch with `ethos mission create --file <yaml>`** then
   **`Agent(subagent_type=<worker>, run_in_background=true)`** — both steps
   are required. Verify the worker is running via TaskList before
   considering the mission active.
4. **The worker commits incrementally.** Each commit:
   - Is one logical step.
   - Passes `make check`.
   - Is locally reviewed by `code-reviewer` and `silent-failure-hunter`
     agents before the next commit lands.
   - Is locally smoke-tested if it touches anything user-visible.
   - Does not accumulate more than 30 minutes of uncommitted changes.
5. **After all commits are in:** `make snapshot-parity` runs end-to-end.
   Manual smoke test of the affected MCP tools by the COO before push.
6. **PR opens.** Copilot review requested once. Polling loop monitors CI.
7. **Address every comment.** No suppressions. No "this is fine."
8. **Resolve threads, merge, delete branch, pull main.** Inner loop done.

## Test pyramid for the migration

| Tier | Where | What it covers |
|------|-------|----------------|
| **Characterization (PR 0)** | `tests/characterization/snapshots/` | Every MCP tool input → response captured on `main`. Replayed in CI on every PR. Catches output-level regressions. |
| **Domain unit (PR 1 onward)** | `tests/domain/` | `Display.apply(client, update)` returns the expected Event or Error. Ownership, cycle, type, duplicate-id invariants enforced. Single-runtime tests per `domain-model.md` §"Testability". |
| **Render unit (PR 3 onward)** — NEW | `tests/render/` | Per-element-kind render tests against `Surface.RECORDING`. Construct an Element, render it via the Recording renderer, assert on the captured calls. Closes the rendering-layer test gap that existed since the project began. |
| **Behavior unit (PR 5 onward)** — NEW | `tests/behavior/` | Element behavior methods (`on_click`, `on_value_change`, etc.) tested directly. Construct an Element, call its behavior method, assert on the emitted InteractionMessage shape. |
| **Family integration (PR 3 onward)** | `tests/integration/families/<family>/` | End-to-end exercise of one element family through the io-model pipeline (decoder → domain → renderer). |
| **Manual smoke (every PR)** | Run by the agent | `make install` + restart `luxd` + exercise the changed MCP tools in a real Claude Code session. Paste the actual output in the PR description. |

## Methods considered and rejected (path only)

The architectural target (DES-031, DES-032, DES-033, io-model.md, domain-model.md)
is **not under review**. Reviewers are scoped to migration **path** only.

For the record: three migration methods were evaluated by three architect
reviewers (`rej` Smalltalk/refactoring school, `kwb` TDD/XP school, `rop`
Plan 9 simplicity school) during the original plan drafting (2026-05-22).
Verdicts:

| Method | Description | Verdict | Reason |
|--------|-------------|---------|--------|
| **A — Horizontal Bands** | One architectural concept per PR across the whole codebase. ~7 PRs, each cross-cutting. | ITERATE (3/3) | The final "all kinds migrated and old paths deleted" PR in this method is a flag day. Empty infrastructure ships before any consumer. The shadow-Display tax has no production value. |
| **B — End-to-End Vertical Slices (amended)** | Infrastructure ships with its first production consumer (basics family) in one PR, then family-by-family migration with each PR deleting its own old path. | **SELECTED** | Each PR is a rollback-coherent unit. Infrastructure does not exist without a production caller (The Bar §5 / PY-RF-2). Two vocabularies never coexist for the same noun longer than one PR. Snapshot parity from PR 0 is the safety net. Adopted as the active plan; PR 3 of this revision continues the same method by pairing io-model infrastructure with basics refactor. |
| **C — Parallel Universe Cutover** | Build a complete second implementation under `domain/`. Cut over with a one-line-per-tool flip. Delete old code. 3 PRs. | REJECTED (3/3 REJECT) | The canonical big-bang rewrite pattern. PR 1 has no production consumer until the flip; the flip surfaces every assumption error simultaneously. |

The revised plan PRs 3+ continue Method B. The same vertical-slice discipline
applies: PR 3 ships io-model infrastructure with basics as its first consumer,
PR 4 brings the remaining basics onto the same shape; PR 5 brings inputs; and so on.

## Open work tracker

Track via `bd` in the `repo:lux` label. Existing beads:

- `lux-jk8m` — was "PR 3: layout family migration." Per this revision, layout
  is now PR 6. The bead can be updated in place to reflect the new
  numbering and the io-model requirement.
- Additional beads for PRs 3, 4, 5, 7, 8, 9, 10, 11, 12, 13 of this revision: TBD —
  to be created when the operator authorizes proceeding.

Do not work two PRs in parallel on the same working tree.

## References

- `docs/architecture/domain-model.md` — the algebra this plan realizes
- `docs/architecture/io-model.md` — the I/O architecture (Decoder / Element / Renderer)
- `docs/architecture/x11-model.md` — the topology PR 13 splits into
- `docs/architecture/introspection-api.md` — already-implemented query pattern
- `docs/oo-refactor/resume.md` — current OO scores; updated after each PR
- `DESIGN.md` DES-030 — three-layer type model (wire / scene graph / snapshot)
- `DESIGN.md` DES-031 — Domain Model Across All Tiers
- `DESIGN.md` DES-032 — Element Owns Behavior, Not I/O
- `DESIGN.md` DES-033 — Renderer and Decoder Families with Asymmetric Cardinality
- `DESIGN.md` DES-034 — IPC and Rendering Are Decoupled — Renderer vs Encoder Distinction
- `DESIGN.md` DES-035 — Handler Routing — Ownership, Client Kind, and Pattern Are Three Independent Axes
- `DESIGN.md` DES-036 — Observer Pattern at the MCP Boundary
- `punt-labs/.claude/rules/python-*.md` — the rules every mission YAML cites
