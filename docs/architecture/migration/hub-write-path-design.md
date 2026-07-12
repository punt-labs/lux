# Hub-Authoritative Write Path — Design

**Status:** design, ratified by the operator with amendments (A1, A3–A6) and the
homogeneous-composite simplification. No implementation dispatched. Derived from
the target architecture, not from any in-progress write code.
**Author:** gvr
**Scope:** the Hub-authoritative *write* contract — field-patch an element,
remove an element, clear a scene — for **both** migrated (Element-ABC) and
not-yet-migrated (legacy wire-dataclass) element kinds, mid-migration, without a
legacy-vs-ABC fork that has to be unwound later.
**Relationship to the migration:** writes are the third leg of the Hub/Display
model, after install ([`show`](../target/target.md)) and interaction dispatch
(D21). This document specifies the leg; it does not migrate any kind. On any
conflict with [`target.md`](../target/target.md), the target wins.

## Abstract

A write is a mutation of authoritative UI state: change one field on an existing
element, remove an element and its subtree, or clear a client's scene. Today the
Hub already installs trees ([`show`](../target/target.md)), removes subtrees, and
re-pushes whole UIs; the store gate for *field mutation*, however, is asymmetric
— an in-place patch lands on an Element-ABC object but is refused against a
frozen legacy wire dataclass. This design defines one write contract that both
element models satisfy. The contract is narrow, id-addressed, absolute, and
idempotent; `id` and `kind` are immutable and unknown fields are rejected; it
validates and coerces with the same walk `show` uses; it enforces ownership; it
commits all-or-nothing; and after a commit it re-pushes the affected UI so the
Display reflects the Hub. The legacy/ABC difference is confined to a *single
polymorphic seam* — the same `isinstance(element, AbcElement)` gate the store
already uses — behind which an ABC element is mutated in place and a legacy
element is realized with `dataclasses.replace()` on its frozen instance. A
crucial simplification frames the whole design: **composites are homogeneous** —
all-ABC or all-legacy, never mixed. An ABC composite's descendants are all ABC
(in-place-patchable at any depth, wiring preserved); a legacy composite's
descendants are all frozen values. So `replace()` on a legacy root is
unconditionally lossless, and the once-feared "stateful ABC leaf inside a legacy
composite" case cannot arise. The seam is *deletable* at migration's end — no
legacy elements, delete the branch — and the amendments A1/A3/A4/A5 are what make
it *correct during* the mixed period, not merely deletable at the end.

## Motivation

### Why Hub-authoritative writes

The Hub wins every disagreement; the Display is a replica
([target.md](../target/target.md)). Install already honors this — a tree is
decoded, validated, and installed into `HubDisplay` before the Display sees a
copy. Mutation must honor it identically. A field change that the Display applied
locally, or that skipped validation, or that a non-owner could trigger, would
make the Display a second authority for that element. The write path closes that
gap: every mutation is an authoritative operation on the Hub store, and the
Display learns of it only through the same replicated re-push it already
consumes.

### Why now, and why it looked hard

The catalog is mid-migration: a handful of kinds are Element-ABC objects that own
data *and* behavior; the rest are frozen wire dataclasses
([element-contract.md](../target/element-contract.md)). The two models differ in
exactly the dimension a field-patch touches:

- An **Element-ABC** object is identity-bearing. It carries live handler
  registrations, property observers, and a mutable field surface with typed
  `_set_<field>` setters and an `apply_patch` that snapshots-and-restores. You
  mutate it in place; its identity — and its wiring — survive the change.
- A **legacy wire dataclass** is a frozen value object. It has no handlers, no
  observers, no setters, and cannot be mutated in place. Its entire meaning is
  its wire fields.

So "patch a field" has two realizations. The naive reading is that the write path
must branch on the element model and carry that branch until migration ends — a
temporary fork. The operator's constraint is that there be *no such fork to
unwind*. The homogeneous-composite simplification (§6.1) plus a single
value-identity mechanism (§6.2) resolve it: the branch that remains is a dead
`else` at migration's end, deleted rather than re-plumbed.

## 1. Terms

- **Write** — a state mutation submitted by a client: a field-patch, an element
  removal, or a clear. Distinct from *install* (`show`) and from *interaction*
  (a click routed back to the Hub).
- **Addressed element** — the element a write names by `(scene_id, element_id)`.
- **Enclosing root** — the scene-root under which the addressed element sits. For
  a root-level write the addressed element *is* the enclosing root.
- **ABC element / legacy element** — an Element-ABC object / a frozen wire
  dataclass, distinguished at runtime by `isinstance(element, AbcElement)`.
- **Homogeneous composite** — a composite whose descendants are entirely ABC or
  entirely legacy; the migration admits no mixed composite (§6.1).
- **Batch** — one or more writes submitted as a unit. A single-field patch is a
  batch of one.
- **Affected root set** — the set of enclosing roots touched by a batch. Commit
  and re-push granularity is the root (§5).

## 2. The client-facing contract

The contract a client sees is deliberately model-agnostic. A client never knows,
and must not need to know, whether an element it addresses is ABC or legacy.

1. **Operations are the typed `Update` vocabulary.** `SetProperty(scene, id,
   field, value)` patches one field; `RemoveElement(scene, id)` removes an
   element and its subtree; a clear removes a client's roots in a scene (§5.3).
   These already exist as frozen, codec-bearing domain types with a discriminated
   `kind`. Insert/replace of a whole root is `AddElement`.
2. **Writes are id-addressed, never positional.** A write names an element (and,
   for a container sub-part, a stable sub-id per
   [element-contract.md](../target/element-contract.md) §Sub-Element Addressing).
   No write references a positional index into a children list.
3. **Writes are absolute, not relative.** `SetProperty` carries the *new value*,
   not a delta. There is no "increment", "append", or "toggle" at the wire level;
   those are computed by the client and submitted as the resulting absolute
   value. This is what makes a write idempotent (§4.2).
4. **`id` and `kind` are immutable; unknown fields are rejected.** A `SetProperty`
   whose `field` is `id` or `kind`, or names a field the target does not have, is
   rejected before any mutation (§4.7).
5. **The response is an ack or a rejection — never both, never neither.** A batch
   that commits returns an ack. A batch rejected for any reason returns the
   reason: a validation report naming each offending element's `id` and `kind`
   (§4.4), an ownership error (§4.3), a not-found error, or a field-constraint
   error (§4.7). The ack is distinguishable from every rejection, so an agent can
   verify the outcome without inspecting pixels
   ([introspection-api.md](../target/introspection-api.md)).
6. **`show` is always available as the whole-tree write.** Any mutation
   expressible as "the tree now looks like this" can be submitted as a `show` of
   the amended tree. `update` is the *narrow* form — a small message for a small
   change — offered where the Hub can realize it authoritatively and
   consistently. Where it cannot (§6.4), the client uses `show`. The two are not
   rivals; `update` is an optimization over the always-correct `show`.

## 3. The store already does most of this

Three of the write path's obligations are already met by the authoritative
store, uniformly across both element models, and the design keeps them:

- **Removal of a subtree** drops the addressed element and every descendant from
  the index, owners, roots, and child-edge collaborators. For an ABC root the
  property-observer cascade prunes the live composite; for a wire-only subtree
  the child-edge walk is the sole removal path. Either way the storage cleanup is
  model-agnostic.
- **Ownership** is recorded per element at install and checked before any
  mutation; a non-owner is refused, an unknown element yields a distinct
  not-found error.
- **Whole-scene replace** (a re-`show`) removes a connection's prior roots and
  re-installs the new ones through the single install path, so ownership, root
  observers, and child indexes are rebuilt in one place.

The one obligation *not* uniformly met is **field mutation**: an in-place patch
lands on an ABC element and is refused against a frozen legacy element. That
refusal is the whole of the problem the design solves (§6). Everything else here
composes mechanisms that already exist and already treat the two models alike.

## 4. Invariants

Each invariant is stated as a property the contract guarantees, followed by the
mechanism that realizes it. Mechanisms are described, not coded — the
implementation chooses the write set.

### 4.1 Atomicity — a batch is all-or-nothing

**Property.** If any write in a batch is rejected — malformed result, ownership
violation, unknown target, forbidden field — *no* write in the batch takes
visible effect. A batch either commits entirely or changes nothing observable.

**Mechanism.** Two phases with a snapshot boundary, generalizing the
snapshot-and-restore a single ABC `apply_patch` already performs, from one
element to the batch:

1. **Stage.** For every write, resolve the target, check the field constraints
   (§4.7), check ownership, and compute the *candidate* post-write state of its
   enclosing root without publishing it. Snapshot enough to restore the store
   exactly. Apply the mutations against the store.
2. **Validate then commit-or-restore.** Run the validation walk over the affected
   root set (§4.4). If the report is empty *and* every check passed, commit —
   re-push each affected root once (§4.5). Otherwise restore every snapshot,
   leaving the store bit-for-bit as it was, and return the reason.

**Snapshot breadth (A5).** For an in-place ABC patch, the snapshot is the touched
object's field state. For any realization that *reinstalls a subtree* — a legacy
composite `replace()`, or an `AddElement` upsert — the snapshot must capture the
full **storage delta**: the index bindings, ownership records, root registrations,
child-edges, and any registered observers for every element added or dropped, not
merely the top index binding. A restore that misses an edge leaves an orphaned
index entry or a stranded observer. The commit granularity is the root, which is
also the re-push granularity and the legacy-realization granularity (§6), so the
three stay aligned.

### 4.2 Single authoritative mutation; idempotent re-push

**Property.** The authoritative effect of a write happens exactly once. A
transport retry of the same write request must not double-apply it. Only the
Hub→Display re-push is repeated on retry, and repeating it is harmless.

**Mechanism.** The write path separates the *authoritative mutation* (once,
against the store) from the *replication* (a whole-UI re-push, idempotent by
construction — replacing the Display's copy with the same tree twice yields the
same Display). Retry-safety of the *client request* comes from the operations
being absolute and id-addressed (§2.3):

- `SetProperty` to an absolute value is idempotent — applying `field = Y` twice
  yields `Y`.
- `RemoveElement` is idempotent — removing an already-absent element is a no-op.
- Clear is idempotent — clearing already-cleared roots is a no-op.
- `AddElement` is the one non-idempotent operation: adding twice would duplicate.
  The contract therefore requires `AddElement` against an existing `id` to be an
  **upsert**, and the upsert must **remove-first**: tear down the prior root of
  that id — its index entries, child-edges, *and its registered observers* —
  before installing the new one. A replace that installs over the old root
  without removing it would register a second root observer and leave duplicate
  child-edges. Remove-first makes re-execution land the same authoritative state
  rather than a second copy or a doubled observer.

With every operation idempotent, a retried request re-runs the pipeline and
converges to the *same* authoritative state; the mutation's observable effect is
"once" without a dedup ledger. If a future non-idempotent operation is ever
needed, it must carry a client-supplied idempotency key that the Hub dedups; the
present contract avoids that by construction.

### 4.3 Ownership

**Property.** In a multi-client Hub, a write to an element the caller does not own
is rejected before any mutation. An unknown element yields a not-found error
distinct from the not-owner error.

**Mechanism.** Every element records its installing connection at install time.
The staging phase (§4.1) checks ownership for *every* target in the batch before
applying anything. A not-owner target fails the batch with an ownership error
naming the attempting and owning connections; an unknown target fails with a
not-found error from the storage lookup. The two vocabularies stay distinct so a
client can tell "you may not" from "there is nothing there."

### 4.4 Validation and coercion parity with `show`

**Property.** A write that would leave the affected root — the addressed element
or any element in its tree — in a state that does not fit its widget is rejected,
with the *same* semantics `show` uses to reject a malformed tree: collect every
error, name each offending element by `id` and `kind`, install nothing.

**Mechanism.** Reuse the existing hierarchy-walking validator. After staging
(§4.1), run the walk over each affected root's *candidate* state. Because both
element models already expose self-validation and child enumeration to that walk
— the ABC by default, the wire dataclasses by opting in — the walk is
model-agnostic and needs no write-specific logic. A non-empty report fails the
batch and is returned to the agent verbatim, exactly as a malformed `show` would
be. The same post-stage walk is where any per-kind value coercion applies to the
new field value; the legacy realization (§6.2) therefore does not need a codec
round-trip to coerce — it sets the raw value with `replace()` and lets the shared
walk validate and coerce, exactly as it does for a freshly-shown tree. This makes
"validate before it becomes authoritative" one rule with one implementation,
shared by install and write.

### 4.5 Hub/Display consistency

**Property.** After any committed write, the Display reflects the Hub. A clear
affects only the calling client's roots and leaves other clients' roots standing.

**Mechanism.** Commit re-pushes each affected root as a whole (the target's
replication policy: resend the affected UI, let the Display replace its copy, let
ImGui re-render). No field-level diff crosses the wire; the Display never applies
a mutation locally. Clear is scoped to the caller: it removes exactly the roots
the calling connection owns in the target scene, then re-pushes the now-smaller
scene; roots owned by other connections are untouched. If a scene loses its last
root the display falls back to its idle surface — a property of an empty scene,
not a special case of clear.

### 4.6 Uniform treatment

**Property.** Legacy and ABC elements flow through the *same* write contract: same
`Update` vocabulary, same field constraints, same ownership gate, same validation
walk, same atomicity boundary, same re-push. A client cannot tell, from the
contract, which model backs an element it writes.

**Mechanism.** §6. The single point at which the two models differ — how a field
mutation is *realized* on the stored object (in-place `apply_patch` vs
`dataclasses.replace()`) — is pushed behind one polymorphic seam so the write
path above it has no branch. The field-constraint checks (§4.7) are applied
before the seam, so both models reject the same forbidden writes for the same
reasons.

### 4.7 Field-write constraints — `id`/`kind` immutable, structural and unknown fields rejected

**Property (A3, A4).** A `SetProperty` targeting `id` or `kind`, naming a
*structural* field (`children`/`pages`, which carry child Elements), or naming a
field the element does not have, is rejected for *both* models, before any
mutation.

**Mechanism, and why it matters.**

- **`id` immutable (A3).** The value-identity argument (§6.1) requires it: an
  element's identity is its `id` plus its fields, and its `id` is the store's
  index key. Letting a write change `id` would either orphan the index entry or
  silently re-key it under a value the client did not install. Reject
  `field == "id"`.
- **`kind` immutable (A3).** `kind` is the element's type discriminator. Changing
  it would morph a `text` into a `button` in place — a different element, a
  different contract, a different renderer. That is a remove-and-add, not a field
  patch. Reject `field == "kind"`.
- **Unknown field rejected uniformly (A4).** An ABC patch already fails on an
  unknown field — the setter lookup finds no `_set_<field>`.
  `dataclasses.replace()` likewise raises on an unexpected keyword. So both
  realizations reject an unknown field *naturally*; the contract makes that a
  stated, uniformly-mapped rejection rather than two divergent exceptions. This
  closes the uniformity gap a dict-amend realization would have opened — a raw
  dict merge would have silently accepted a nonexistent field and carried garbage
  into the wire form.
- **Structural field deferred to `show`.** A field that *carries* child Elements —
  `children`/`pages` on a legacy composite — is refused by the same pre-seam gate.
  Value-replacement rebinds only the root's index entry, installing no new children
  and evicting no old ones; accepting the patch would desync the Hub index from the
  rendered tree (§6.2/§6.4). The ABC path already rejects these as unknown fields
  (no `_set_children` setter); the gate names the structural reason and applies the
  same rejection to the legacy path, which would otherwise mutate the store.

### 4.8 Display-state survival across re-push (A6)

**Property.** Transient display-side widget state — table row selection, scroll
position, tree expansion, in-progress text entry — is keyed by stable element and
sub-part `id`, and **must survive a whole-root re-push**.

**Mechanism, and why it matters.** A narrow `update` to one field nonetheless
triggers a whole-root resend (§4.5): the Display replaces its copy of that root.
If the Display keyed any transient state positionally, or by object identity, that
state would be destroyed on every field update — a user's scroll would jump, a
half-typed input would clear, an expanded tree would collapse, each time an agent
patched an unrelated field. The write path relies on the Display keying *all* such
state by the stable ids the element contract already mandates
([element-contract.md](../target/element-contract.md) §Sub-Element Addressing), so
that a replaced-but-equal subtree re-adopts its prior transient state. This is a
requirement the write path *depends on* but does not itself own; it is stated here
because the narrow-update ergonomics stand or fall on it (§8, hardest risk).

## 5. Write shapes

### 5.1 Field-patch

`SetProperty(scene, id, field, value)`. Resolve, check field constraints (§4.7),
check ownership, compute the candidate (§6), validate the enclosing root,
commit-or-restore, re-push. The addressed element may be a root or, for ABC,
nested at any depth; the realization (§6) depends on whether the addressed element
is ABC or legacy and, for legacy, whether it is a root (§6.4).

### 5.2 Remove

`RemoveElement(scene, id)`. Storage removal is already model-agnostic (§3). For an
ABC element the observer cascade keeps the parent composite's child tuple
consistent; for a legacy *root* the root simply leaves the index and `scene_roots`
and the re-push omits it. Removal of a legacy element *nested below* a legacy
composite is deferred on the same grounds as nested legacy field-patch (§6.4).

### 5.3 Clear

Remove all roots the calling connection owns in the target scene, scoped per
§4.5. Clear is a batch of `RemoveElement`s over the caller's owned roots; it
inherits atomicity, ownership, and re-push from the batch pipeline.

## 6. Coexistence: the central question, simplified

> Legacy elements do not implement the ABC write surface — no `apply_patch`, no
> `_set_<field>` setters, and they are frozen. How does a Hub-authoritative field
> mutation work for a legacy element without a hack, and without a fork that must
> be unwound when migration ends?

### 6.1 The framing simplification — no mixed composites

The migration admits **no mixed composites**. A composite is homogeneous:
entirely ABC or entirely legacy. This is the invariant the all-ABC gate and
legacy-forcing establish under [DES-041](../../../DESIGN.md) — an ABC container is
chosen only when its whole subtree is migrated-ABC, and a legacy container forces
its descendants legacy. The write path *depends* on this invariant; any decode
path that would admit a mixed composite is a conformance bug against DES-041, not
a case the write path must tolerate.

Two consequences frame everything below:

- An **ABC composite's descendants are all ABC** — every one is in-place-patchable
  at any depth, with its handlers and observers preserved, and every mutation is
  visible through the parent because the parent holds the same object.
- A **legacy composite's descendants are all frozen values** — no descendant
  carries live wiring. Rebuilding a legacy subtree loses nothing, because there is
  nothing but values to reproduce.

The once-feared case — a stateful ABC leaf (a button, a checkbox) nested inside a
legacy composite, whose wiring a rebuild would silently drop — **cannot occur.**
It is removed from the design. There is no "scan the subtree for stateful ABC
descendants before rebuilding" step, because it would guard a state DES-041 does
not permit.

### 6.2 The chosen mechanism — one seam; `replace()` for legacy (A1)

Define field mutation as a single conceptual operation — "return the
authoritative element that results from setting `field = value`, preserving
identity" — and let the two models realize it honestly:

- **ABC element:** apply the patch in place; the object *is* the identity, so
  identity, handlers, and observers are preserved. This is the existing
  `apply_patch` with its snapshot-and-restore.
- **Legacy element (A1):** produce the replacement with
  `dataclasses.replace(element, **{field: value})`. `replace()` constructs a new
  frozen instance that **shares the element's other fields and children by
  reference** and overrides only the addressed field. Identity is preserved
  because a value object's identity is its `id` and fields, and the replacement
  carries the same `id`. For a **scalar/leaf field** this is lossless: the
  untouched children are shared by reference, and — because an all-legacy
  subtree's descendants are frozen values (§6.1) — nothing but values is
  reproduced. It is also cheaper than a codec round-trip. Value coercion is not
  needed at this step: the post-stage validation walk (§4.4) coerces and validates
  the new value exactly as it would for a shown tree. `replace()` also rejects an
  unknown field by raising, satisfying §4.7 without extra code.

  A **structural field** — one that *carries* child Elements, concretely
  `children` and `pages` on a legacy composite — is the one case value-replacement
  cannot realize, and it is refused before the seam (§4.7 gate, alongside the
  immutable `id`/`kind`). Rebinding the root's index entry installs no new child
  (no index, owner, or child-edge is created) and evicts no old one, so the
  Display would render a child the Hub index does not know — a click resolving to
  nothing — while the old children linger. So a structural field defers to `show`,
  which rebuilds the subtree correctly, on the same fail-loud grounds as a
  nested-legacy write (§6.4).

The write path above this seam does not branch. It asks the store to realize the
mutation and rebinds to the result; the result is `self` for ABC and a fresh
frozen instance for legacy. The *only* discriminator is the `isinstance(element,
AbcElement)` check that already gates root-observer registration, removed-flag
reads, and the current field-mutation refusal in the store. No new cross-cutting
interface is introduced: the "common write surface both models satisfy" is the
union of contracts both models *already* have (the `Update` vocabulary, the
validation walk, and — for legacy — the frozen-dataclass `replace()` the stdlib
provides). ABC merely offers in-place patch *in addition*, which the seam prefers
when present. The legacy realization **touches no legacy class**: no `apply_patch`
retrofit, no setters, no unfreezing.

### 6.3 Why the seam is not a fork to unwind — and what makes it correct *now*

Two distinct claims, and the design needs both:

- **Deletable at the end.** At migration's end there are no legacy elements; the
  legacy branch of the seam has zero live inputs. Removing it is a **deletion of a
  dead branch**, not a rework — the ABC branch is already the complete, permanent
  design and needs no change when the legacy branch goes. That is the difference
  between debt (plumbing that must be re-threaded) and correct polymorphism (an
  `else` that is deleted).
- **Correct during.** Deletability at the end does *not* by itself make the mixed
  period correct. What makes it correct now are the amendments: `replace()` over
  homogeneous legacy subtrees (A1, lossless), immutable `id`/`kind` and
  unknown-field rejection (A3/A4, so a value replacement cannot corrupt identity
  or carry garbage), and the full storage-delta snapshot with remove-first upsert
  (A5, so atomicity and observer counts hold). "Debt-free" here means *both*
  deletable at the end *and* correct throughout — not "provisionally acceptable
  until we fix it."

### 6.4 The deferred corner — nested mutation below a legacy composite

One case is deliberately out of scope, and the reason is now honest and simple.

A legacy **root** — whether a leaf or a composite — is writable **for its
scalar/leaf fields**: patch the field via `replace()`, rebind the index, re-push.
Because the root has no parent, there is no stale reference to reconcile, and
because its subtree is all-legacy (§6.1) the `replace()` is lossless for those
fields. The "restricted-to-no-stateful-ABC-descendant" qualifier from earlier
drafts is moot and removed: under §6.1 there are no such descendants to worry
about.

The one exception is a **structural field** on that root — `children` or `pages`,
which carry child Elements. Value-replacement rebinds only the root's index entry;
it installs no new children and evicts no old ones, so accepting such a patch
would desync the Hub index from the rendered tree (a new child renders but
resolves to nothing on interaction; the old children linger). A structural-field
patch therefore defers to `show`, fail-loud, on the same grounds as a nested
mutation below — the client resends the amended tree, and install rebuilds the
subtree correctly.

A legacy element **nested below a legacy composite** is *deferred*. To patch such
a child, the store would rebind its index entry, but the frozen legacy parent
still holds the old child by reference; keeping the rendered tree consistent would
require rebuilding the whole spine from the root down to the addressed element —
each frozen ancestor `replace()`d with amended children. That spine-rebuild is
buildable and, under §6.1, would be lossless. **We choose not to build it.** This
is a pure simplicity choice — do not build spine-rebuild machinery for the mixed
period — *not* a hazard-avoidance measure. The old justification (a rebuild might
drop a nested ABC leaf's wiring) is void: mixed composites do not exist, so there
is no wiring to drop. The deferral is scope, not danger.

The client is not stranded. `show` of the amended tree writes any element at any
depth, because whole-UI-resend is the architecture's baseline replication model.
A nested-legacy write is therefore rejected fail-loud, with an error naming the
containing root's kind and directing the client to resend via `show`. The
rejection deletes itself the moment that container kind migrates to ABC — after
which in-place patch reaches every descendant.

Capability matrix at any migration state:

- **Complete and clean now:** clear (per-connection scoped); add/replace/remove of
  any root; field-patch and removal of any **ABC** element at **any depth**;
  scalar/leaf field-patch and removal of a legacy **root** (leaf or composite) via
  `replace()`.
- **Deferred, self-deleting, never a dead-end:** a **structural** field-patch
  (`children`/`pages`) on any element, and field-patch or nested removal of a
  legacy element **below a legacy composite** — rejected fail-loud; the client
  resends via `show`. The rejection vanishes when the container migrates (for the
  nested case) or is intrinsic to whole-subtree edits (for the structural case).

This matches the migration's grain: the ABC frontier is fully writable at any
depth, legacy roots are writable, and the one residual gap is exactly the case the
migration is actively retiring — with `show` as the always-correct escape the
whole time.

## 7. Rejected alternatives

- **Legacy field-mutation via `to_dict` → amend → `from_dict` codec round-trip.**
  Strictly worse than `dataclasses.replace()` (A1). It re-serializes and
  re-decodes the whole element and its children to change one field, re-running
  child codecs and allocating a fresh subtree, where `replace()` shares the
  untouched fields and children by reference. A raw dict-amend variant is worse
  still: it would silently accept a nonexistent field, defeating §4.7's uniform
  unknown-field rejection. Rejected as the realization; `replace()` supersedes it.
- **Retrofit `apply_patch` / typed setters onto every frozen legacy dataclass.**
  Brings the ABC *write* surface onto legacy classes ahead of their migration. A
  bridge that must be unwound — those methods are ripped out or collide when the
  kind migrates — and it contradicts the rule that behavior rides *with* each
  kind's migration, not through a separate sweep over legacy kinds. Rejected.
- **Unfreeze legacy dataclasses to allow in-place `SetProperty`.** Frozen is a
  deliberate property of wire value types; unfreezing to enable mutation trades a
  correctness invariant for a mechanism the value model does not need (§6.1), and
  `replace()` already writes a frozen instance without unfreezing anything.
  Rejected.
- **Wrap each legacy element in a `LegacyElementAdapter` faking the ABC interface
  at write time.** A classic bridge object — precisely the "hidden transport
  adapter" the element contract forbids
  ([element-contract.md](../target/element-contract.md) §What Elements Must Not
  Become). Deleted at migration end: debt. Rejected.
- **Build spine-rebuild for nested-legacy writes now.** Buildable and, under
  §6.1, lossless — but it is machinery whose only purpose is the mixed period, and
  `show` already covers the case correctly. Deferred by choice (§6.4), not
  rejected on correctness; revisit only if a concrete need outweighs the
  always-available `show`.
- **Support mixed composites (an ABC leaf inside a legacy container, or the
  reverse).** This is what would have forced a subtree scan before any legacy
  rebuild and reintroduced the drop-the-wiring hazard. The migration excludes it
  by design (§6.1); the write path assumes its absence. Rejected as a thing to
  support.
- **A field-level diff protocol to the Display.** The target explicitly defers a
  diff protocol until a real performance problem appears; writes re-push whole
  UIs. A diff protocol would also reintroduce Display-side mutation application,
  eroding the single-authority rule. Rejected.
- **A single uniform "always `replace()`" realization across both models.**
  Applying value-replacement to ABC elements too would drop their handler and
  observer wiring on every patch. Uniformity that corrupts the identity-bearing
  model is not uniformity worth having. Rejected.

## 8. What is genuinely hard, honestly

The homogeneous-composite simplification (§6.1) removed what had been the central
hazard — a rebuild silently dropping a nested ABC leaf's wiring — so the deep
correctness trap is gone. What remains is real but bounded:

- **Display-state survival across whole-root re-push (§4.8)** is now the sharpest
  live concern. A narrow `update` to one field forces a whole-root resend, and any
  transient display state not keyed by stable id — scroll, selection, tree
  expansion, in-progress text entry — is destroyed unless the Display re-adopts it
  by id. This is a cross-tier dependency the write path relies on but does not
  own: the write contract is Hub-side, the state at risk is Display-side. Getting
  it wrong makes `update` actively unpleasant — every field patch jostles the
  user's place in the UI — without failing any Hub-side test.
- **Batch restore fidelity for subtree-reinstalling realizations (§4.1, A5).** A
  legacy composite `replace()` or an `AddElement` upsert touches index bindings,
  ownership, root registrations, child-edges, and observers. The stage-then-restore
  must snapshot the full storage delta; a snapshot that captures only the top
  binding leaves an orphaned entry or a stranded observer on a mid-batch
  rejection. Solvable, but it is an obligation to discharge deliberately, not a
  freebie.
- **Nested-legacy deferral is a capability gap, not a defect.** During the mixed
  period, patching a legacy element below a legacy composite requires the client to
  resend via `show`. Honest to call it a gap; it closes kind-by-kind as migration
  proceeds, and `show` covers it correctly throughout.

### Hardest unresolved risk

**Display-side transient state survival across the whole-root re-push (§4.8).**
Because the narrow `update` is realized as a whole-root resend, the ergonomics of
every field update depend on the Display keying *all* transient widget state —
selection, scroll, expansion, half-typed input — by the stable element and
sub-part ids the contract mandates, and re-adopting that state when it receives a
replaced-but-equal subtree. The write path cannot enforce this from the Hub side;
it is a property of the renderer. If any transient state is keyed positionally or
by object identity, a single narrow field patch will visibly disturb an unrelated
part of the UI. The mitigation is to make id-keyed re-adoption an explicit,
tested requirement of the Display's replace-copy path — verified through the
introspection surface, not assumed — and to treat any transient state the Display
cannot re-key by id as a reason to prefer a targeted mechanism over a whole-root
resend for that specific widget, should one ever prove necessary.

## 9. Backwards compatibility

The client-facing `show`/`update`/`clear` surface is unchanged in shape; this
design specifies the *authority* and *consistency* semantics behind it, not new
tool signatures. The observable changes are: a *scalar/leaf* field-patch addressed
to a legacy *root*, which the store presently refuses outright, now succeeds via
`replace()`; a field-patch addressed to a legacy element *below a legacy
composite*, or a *structural* field-patch (`children`/`pages`) on any element, is
rejected with a precise, actionable error pointing the client at `show`; and a
`SetProperty` targeting `id`/`kind` or an unknown field is now uniformly rejected
rather than accepted-and-corrupting or divergently-erroring. No element kind's
wire schema changes. No Display-side behavior changes beyond receiving whole-UI
re-pushes it already knows how to apply — subject to the id-keyed transient-state
survival requirement of §4.8.

## Related documents

- [target.md](../target/target.md) — Hub authority, replication policy, front
  doors.
- [ui-model.md](../target/ui-model.md) — `HubDisplay`, handler model, self-
  validation.
- [element-contract.md](../target/element-contract.md) — the common element
  contract, validation contract, sub-element addressing, what elements must not
  become.
- [introspection-api.md](../target/introspection-api.md) — verifying a write's
  outcome, and the id-keyed display-state survival of §4.8, through the live
  system.
- [README.md](./README.md) — the migration strategy ([DES-041](../../../DESIGN.md)
  fork-don't-mix, homogeneous composites) this write path depends on.
