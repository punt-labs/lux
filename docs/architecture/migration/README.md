# Element migration: legacy kinds → distributed Element-ABC / Hub-Display

This directory holds the plan for migrating Lux's element kinds off the legacy
`SceneManager` path and onto the new distributed Element-ABC / Hub-Display
architecture (see [`../target/target.md`](../target/target.md) and the DES-030+
ADRs in [`../../../DESIGN.md`](../../../DESIGN.md)).

- **Audit + per-element map:** [`../element-migration-audit.md`](../element-migration-audit.md)
- **Element #1 design (worked example):** [`progress-element-design.md`](progress-element-design.md)

## Where we are

**4 of 25 element kinds are on the new Element-ABC path** — the io-model kinds
`text` (a display-only leaf) plus the interactive `button`, `checkbox`, and
`dialog`. The other 21 are still
legacy frozen dataclasses on the `SceneManager` + dual-write `DomainPump` path.
Of the 21: ~9 are interactive (need the full D21 remote-dispatch treatment) and
~12 are display-only (need an `ElementABC` with render/id/children but no
handler wrapping); `table` sits on the boundary because it carries built-in
view state.

## Self-validation travels with each migration

Self-validation is **part of what "migrated" means**, not a separate pass over
legacy elements (DES-039). Each element gains its component-appropriate
`validate()` — the walk collects errors across the hierarchy, returns them to
the agent, and an invalid tree is never rendered — as part of its migration in
the per-element process below. A migrated kind that is not self-validating is
not done. The `table` exemplar proved the contract on a known-good shape to
lock its design; from here `validate()` rides with the migration, and there is
no standalone validation sweep on not-yet-migrated kinds. See
[`../target/element-contract.md`](../target/element-contract.md)
§"Validation Contract".

## Ratified design decisions

These five were escalated to the operator and ratified before any implementation
(the "escalate design issues before implementation" rule). They are settled:

1. **One `ElementABC` for everything, not a lighter display-only base.** The
   unused handler/wrap surface on a display-only element costs nothing at
   runtime; a second base doubles the `isinstance` surface for no gain.
2. **Fork, don't mix** (supersedes the earlier "incremental crossing,
   mixed-scene coexistence"). Build the new ABC path as a parallel track;
   legacy and ABC elements do **not** interoperate inside composites. Migrate a
   container early and compose all-ABC, so a new element is never nested in a
   legacy container; where a scene would force it, **duplicate** the element —
   the new ABC class takes the canonical name and the legacy is renamed out of
   the way — rather than bridging. The legacy render/dispatch path is retired
   once every kind has forked across. See [DES-041](../../../DESIGN.md) and
   §Sequencing.
3. **Stateful `table`/`plot`: split by authority.** Ephemeral *view* state
   (filter text, search, scroll, window drag) stays Display-local and is never
   re-pushed; authoritative table *selection* routes to the Hub. `plot` migrates
   as a display-only leaf.
4. **`draw` command families stay a value family, not elements.** Only
   `DrawElement` migrates (display-only leaf); `curve`/`line`/`shape`/`text`
   stay composed value objects. Giving line segments ids and handler registries
   is what the element contract warns against.
5. **Invert the `wrap_handlers_for_remote` seam — DONE (PR #237).** Each
   interactive element declares its interaction via a per-element
   `RemoteDispatchSpec`; the D21 wrap logic iterates the specs instead of
   switching on concrete type (Open-Closed — new interactive elements just
   declare, no `isinstance` branch).

## Sequencing (by testability)

Testing is our choice, so migrate in the order that makes the system
composable and testable soonest (DES-041), bottom-up:

1. **A container first ("a frame")** — `group` or `window` — so there is a
   surface to compose and test on.
2. **Display-only primitives** — `text` (done), plus `image`, `separator`,
   `progress`, `spinner`, `markdown` — content to place in the frame.
3. **Interactive primitives** — `button`/`checkbox`/`dialog` (done), plus
   `slider`, `combo`, `input_text`, `input_number`, `radio`, `color_picker`,
   `selectable`.
4. **Compose increasingly complete widgets** from the primitives + containers.
5. **Complex widgets last** — `table`, `plot`, `draw` (built-in state, most
   surface; nothing testable is gained by taking them early).

**Prerequisite:** the render engine — the Template Method `Element.render()` +
per-kind adapters ([`render-path-unification-design.md`](./render-path-unification-design.md))
— lands first so any migrated kind paints via the new path. Each migrated kind
is an Element-ABC subclass that paints via `Element.render()` and self-validates
([DES-039](../../../DESIGN.md)). The legacy render/dispatch path is retired once
every kind has forked across.

## The per-element process (verify-as-you-go)

The architecture is subtle and the failure mode is an agent proceeding on a
wrong mental model. So every element (or minimal family) goes through this,
deliberately slow, verifying direction at each step:

1. **Design, grounded by exemplar.** Cite the canonical docs (`target.md`,
   `ui-model.md`, `element-contract.md` — never the archived `concepts/`) **and
   the specific working exemplar it copies** (display-only → `Text`, interactive
   → `Button`/`Checkbox`, composite → `Dialog`). Restate, in the designer's own
   words, what crosses the Hub/Display boundary, what is Hub-authoritative, what
   is Display-local — demonstrating understanding, not assuming it. Design by
   analogy to a known-good element, with file:line.
2. **Direction-check with the operator — before any code.** Present the design:
   "this element is like `<exemplar>`; here is how it maps; here is
   authoritative-vs-local." The operator confirms the direction or corrects it.
   This is the checkpoint that catches a wrong model before it becomes wrong
   code.
3. **Implement** (only after ratification) — one element, `make check`,
   incrementally. Implement the kind's component-appropriate `validate()`
   (DES-039) with its validation tests as part of this step; a migrated kind
   that is not self-validating is not done.
4. **Extend introspection so behavior is programmatically verifiable.**
   Introspection must scale with functionality (grounded in
   [`../target/introspection-api.md`](../target/introspection-api.md)). The
   foundational primitive is a per-element `render_path` (`abc` vs `legacy`) plus
   resolved props in `inspect_scene`, so every migration PR asserts "element X
   flipped to the ABC path and its state reads back" without pixel-peeping.
   Interactive elements grow the surface further (assert the D21 handler fired on
   the Hub, the authoritative state changed). The introspection extension ships
   in the same PR as the element it verifies.
5. **Verify live through the NEW path** — render it, interact with it, introspect
   (`inspect_scene`/`list_recent_events`), confirm it behaves via the new
   architecture not the legacy pump. The operator confirms the observed behavior.
   Manual testing is confirmation of the programmatic result, not trial-and-error.
6. **Review + merge** (`gvr` + the PR-review agents).
7. **Direction re-check after it lands** — record what was learned in the audit,
   confirm the mental model still holds before the next element. If an exemplar
   assumption was wrong, correct course before the next one.

One element at a time. No batch dispatch. The grounding-by-exemplar plus the two
direction-checks (design-time and after-landing) are the guards against the
recurring "agent did not understand the design" failure.

## The render engine closes the old "abc ≠ paints" gap

Historically, "on the ABC path" did **not** mean the paint path changed: a
migrated kind's *type*, mutation, codec routing, and HubDisplay installation
flipped, but the live pixels still flowed through the legacy renderer, so
`render_path == "abc"` meant type/routing/HubDisplay, not that
`Element.render()` painted. The **render engine** (the render-path unification —
the Template Method `Element.render()` + per-kind adapters) closes that gap: it
makes `render()` the actual paint path for migrated kinds, so after it lands
`render_path == "abc"` means the element *paints* via the new path. It is the
fork's render engine and lands before any kind migrates onto the new path.

## Tracking

The work is tracked as a beads epic with per-batch child beads. New element kinds
must land on the new path, not the legacy one — adding to legacy increases
migration debt.
