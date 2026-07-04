# Element migration: legacy kinds → distributed Element-ABC / Hub-Display

This directory holds the plan for migrating Lux's element kinds off the legacy
`SceneManager` path and onto the new distributed Element-ABC / Hub-Display
architecture (see [`../target/target.md`](../target/target.md) and the DES-030+
ADRs in [`../../../DESIGN.md`](../../../DESIGN.md)).

- **Audit + per-element map:** [`../element-migration-audit.md`](../element-migration-audit.md)
- **Element #1 design (worked example):** [`progress-element-design.md`](progress-element-design.md)

## Where we are

**4 of 25 element kinds are on the new Element-ABC path** — the interactive
io-model kinds `text`, `button`, `checkbox`, `dialog`. The other 21 are still
legacy frozen dataclasses on the `SceneManager` + dual-write `DomainPump` path.
Of the 21: ~9 are interactive (need the full D21 remote-dispatch treatment) and
~12 are display-only (need an `ElementABC` with render/id/children but no
handler wrapping); `table` sits on the boundary because it carries built-in
view state.

## Ratified design decisions

These five were escalated to the operator and ratified before any implementation
(the "escalate design issues before implementation" rule). They are settled:

1. **One `ElementABC` for everything, not a lighter display-only base.** The
   unused handler/wrap surface on a display-only element costs nothing at
   runtime; a second base doubles the `isinstance` surface for no gain.
2. **Incremental crossing, big-bang deletion.** Kinds flip one family at a time
   (the pump's mixed-scene skip keeps both paths alive during the transition);
   the legacy `SceneManager` / `DomainPump` / `_RENDERERS` dispatch is deleted
   only after the last kind crosses.
3. **Stateful `table`/`plot`: split by authority.** Ephemeral *view* state
   (filter text, search, scroll, window drag) stays Display-local and is never
   re-pushed; authoritative table *selection* routes to the Hub. `plot` migrates
   as a display-only leaf.
4. **`draw` command families stay a value family, not elements.** Only
   `DrawElement` migrates (display-only leaf); `curve`/`line`/`shape`/`text`
   stay composed value objects. Giving line segments ids and handler registries
   is what the element contract warns against.
5. **Invert the `wrap_handlers_for_remote` seam.** Each interactive element
   declares its interaction via a typed descriptor; the D21 wrap logic iterates
   the descriptor instead of switching on concrete type (Open-Closed — new
   interactive elements just declare, no ABC change). **This is a prerequisite
   for the interactive-inputs batch, designed before that batch dispatches.**

## Sequencing

Per the audit, migrate in this order (lowest-risk pattern first, hardest last):

0. **Reconcile the exemplars** — one source of truth for the 4 migrated kinds;
   fix the two shipped inconsistencies (Checkbox omitted from `_ABC_TYPES` and
   from the `_element_to_dict` encode special-case).
1. **Basics display-only leaves** — image, separator, progress, spinner, markdown.
2. **Interactive value inputs** — slider, combo, text/number inputs, radio,
   color picker, selectable. Carries the decision-#5 wrap-seam refactor.
3. **Simple composites** — group, tab bar, collapsing header.
4. **Stateful composites** — window, modal.
5. **Draw and plot.**
6. **Table**, on its own (built-in filter/selection state).
7. **Retire the legacy render path** once every kind has crossed.

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
   incrementally.
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

## A load-bearing subtlety

"On the ABC path" does **not** mean the paint path changed. Migrating a
display-only leaf changes the object's *type*, its mutation (`apply_patch` vs
`dataclasses.replace`), codec routing, and HubDisplay installation — but the live
pixels still flow through the legacy renderer until Batch 7. `render_path == "abc"`
means type/routing/HubDisplay, **not** that `Element.render()` paints. This is the
subtlety most likely to break a wrong mental model.

## Tracking

The work is tracked as a beads epic with per-batch child beads. New element kinds
must land on the new path, not the legacy one — adding to legacy increases
migration debt.
